import calendar
import io
import logging
from pathlib import PurePath

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Sum
from django.http import QueryDict
from PIL import Image, ImageOps
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Categories,
    DispatchPurpose,
    InventoryTransaction,
    ItemCondition,
    ItemSpec,
    ItemStatus,
    ItemSubCategory,
    Items,
    Locations,
    Party,
    Shed,
    StockBalance,
    StockOwner,
    StorageLocation,
    StorageShed,
    StorageType,
    TransactionType,
    Units,
    UserProfile,
)
from .permissions import (
    LocationScopedFieldsMixin,
    is_district,
    is_master,
    is_ndma,
    sees_all_locations,
    user_location_id,
)


def name_field(source):
    """Read-only field that shows a related record's name next to its id."""
    return serializers.CharField(source=source, read_only=True, allow_null=True)


# --- Auth ------------------------------------------------------------------

def user_role(user):
    """The user's role; superusers without the NDMA role count as master."""
    profile = getattr(user, 'profile', None)
    role = profile.role if profile else UserProfile.ROLE_LOCATION
    if user.is_superuser and role != UserProfile.ROLE_NDMA:
        return UserProfile.ROLE_MASTER
    return role


def user_info(user):
    """Who is logged in, their role and which storage location they are limited to (none for master and all areas users)."""
    profile = getattr(user, 'profile', None)
    storage_location = profile.storage_location if profile else None
    location = storage_location.location if storage_location else None
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.get_full_name(),
        'role': user_role(user),
        'storage_location_id': storage_location.st_loc_id if storage_location else None,
        'storage_location_name': storage_location.details if storage_location else None,
        'location_id': location.location_id if location else None,
        'location_name': location.location_name if location else None,
        'can_approve_demands': is_master(user) or is_ndma(user),
    }


class LoginSerializer(TokenObtainPairSerializer):
    """Returns the access/refresh tokens plus the user's role and storage location."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = user_info(self.user)
        return data


# --- Lookup tables ---------------------------------------------------------

class CategoriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categories
        fields = "__all__"


class LocationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Locations
        fields = "__all__"


class ShedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shed
        fields = "__all__"


class StorageTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageType
        fields = "__all__"


class ItemStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemStatus
        fields = "__all__"


class ItemConditionSerializer(serializers.ModelSerializer):
    """A condition under a status, e.g. Non Serviceable -> Expired. Names are unique per status."""
    status_name = name_field('status.status_name')

    class Meta:
        model = ItemCondition
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        status = attrs.get('status', getattr(self.instance, 'status', None))
        name = attrs['condition_name'] = clean_name(attrs.get('condition_name', getattr(self.instance, 'condition_name', '')))
        if name_taken(self, ItemCondition.objects.filter(status=status), 'condition_name', name):
            raise serializers.ValidationError({'condition_name': f'{status.status_name} already has this condition.'})
        return attrs


class UnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Units
        fields = "__all__"


class StockOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockOwner
        fields = "__all__"


class DispatchPurposeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchPurpose
        fields = "__all__"


class TransactionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionType
        fields = "__all__"


class PartySerializer(serializers.ModelSerializer):
    """A supplier, donor or NDMA, under the transaction type it belongs to."""
    txn_type_name = name_field('txn_type.type_name')

    class Meta:
        model = Party
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        txn_type = attrs.get('txn_type', getattr(self.instance, 'txn_type', None))
        name = attrs['party_name'] = clean_name(attrs.get('party_name', getattr(self.instance, 'party_name', '')))
        if name_taken(self, Party.objects.filter(txn_type=txn_type), 'party_name', name):
            raise serializers.ValidationError({'party_name': f'{txn_type.type_name} already has this party.'})
        return attrs


def clean_name(value):
    """Name with surrounding and doubled spaces removed."""
    return ' '.join(value.split())


def name_taken(serializer, queryset, field, name):
    """Names are unique ignoring case and spaces (the database enforces the same)."""
    duplicate = queryset.filter(**{f'{field}__iexact': name})
    if serializer.instance is not None:
        duplicate = duplicate.exclude(pk=serializer.instance.pk)
    return duplicate.exists()


class ItemsSerializer(serializers.ModelSerializer):
    item_category = CategoriesSerializer(read_only=True)
    unit_name = name_field('unit.unit_name')

    class Meta:
        model = Items
        fields = "__all__"

    def validate_item_name(self, value):
        value = clean_name(value)
        if name_taken(self, Items.objects.all(), 'item_name', value):
            raise serializers.ValidationError('This item already exists; add a sub category or spec to it instead.')
        return value


# --- Storage ---------------------------------------------------------------

class StorageLocationSerializer(serializers.ModelSerializer):
    location_name = name_field('location.location_name')
    type_name = name_field('type.type_name')

    class Meta:
        model = StorageLocation
        fields = "__all__"


class StorageShedSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    storage_location_name = name_field('sto_loc.details')
    location_name = name_field('sto_loc.location.location_name')
    shed_name = name_field('shed.shed_name')

    class Meta:
        model = StorageShed
        fields = "__all__"


class StockBalanceSerializer(serializers.ModelSerializer):
    """Quantity on hand; read-only, it follows from the transactions."""
    storage_location_name = name_field('storage_location.details')
    location_name = name_field('storage_location.location.location_name')
    shed_name = name_field('sto_shed.shed.shed_name')
    item_name = name_field('item.item_name')
    category_name = name_field('item.item_category.category_name')
    sub_cat_name = name_field('sub_cat.sub_cat_name')
    spec_name = name_field('spec.spec_name')
    status_name = name_field('status.status_name')
    condition_name = name_field('condition.condition_name')
    owner_name = name_field('owner.owner_name')
    unit_name = name_field('item.unit.unit_name')

    class Meta:
        model = StockBalance
        exclude = ['row_id']


class TotalInventorySerializer(serializers.Serializer):
    """Read-only serializer for aggregated total inventory per item, sub category, spec and status."""
    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    item_code = serializers.CharField(allow_null=True)
    category_name = serializers.CharField(allow_null=True)
    sub_cat_id = serializers.IntegerField(allow_null=True)
    sub_cat_name = serializers.CharField(allow_null=True)
    spec_id = serializers.IntegerField(allow_null=True)
    spec_name = serializers.CharField(allow_null=True)
    status_id = serializers.IntegerField()
    status_name = serializers.CharField()
    condition_id = serializers.IntegerField()
    condition_name = serializers.CharField()
    owner_id = serializers.IntegerField()
    owner_name = serializers.CharField()
    total_quantity = serializers.DecimalField(max_digits=15, decimal_places=2)
    unit = serializers.CharField(allow_null=True)
    stock_entries = serializers.IntegerField()


# --- Item sub categories and specs -------------------------------------------

def specs_for(item_id, sub_cat_id=None):
    """Active specs to choose from for an item: the whole item's and, with a sub category, that sub category's."""
    specs = Q(sub_cat__isnull=True)
    if sub_cat_id is not None:
        specs |= Q(sub_cat_id=sub_cat_id)
    return ItemSpec.objects.filter(specs, item_id=item_id, is_active=True)


class ItemSubCategorySerializer(serializers.ModelSerializer):
    item_name = name_field('item.item_name')

    class Meta:
        model = ItemSubCategory
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        item = attrs.get('item', getattr(self.instance, 'item', None))
        name = attrs['sub_cat_name'] = clean_name(attrs.get('sub_cat_name', getattr(self.instance, 'sub_cat_name', '')))
        if name_taken(self, ItemSubCategory.objects.filter(item=item), 'sub_cat_name', name):
            raise serializers.ValidationError({'sub_cat_name': 'This item already has this sub category.'})
        return attrs


class ItemSpecSerializer(serializers.ModelSerializer):
    item_name = name_field('item.item_name')
    sub_cat_name = name_field('sub_cat.sub_cat_name')

    class Meta:
        model = ItemSpec
        fields = "__all__"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        item = attrs.get('item', getattr(self.instance, 'item', None))
        sub_cat = attrs.get('sub_cat', getattr(self.instance, 'sub_cat', None))
        if sub_cat is not None and sub_cat.item_id != item.pk:
            raise serializers.ValidationError({'sub_cat': 'This sub category is not of the chosen item.'})
        name = attrs['spec_name'] = clean_name(attrs.get('spec_name', getattr(self.instance, 'spec_name', '')))
        if name_taken(self, ItemSpec.objects.filter(item=item, sub_cat=sub_cat), 'spec_name', name):
            raise serializers.ValidationError({'spec_name': 'This spec already exists.'})
        return attrs


def item_options(item):
    """An item's active sub categories, each with its specs, plus the specs of the whole item."""
    specs = list(item.specs.filter(is_active=True).order_by('spec_name').values('spec_id', 'spec_name', 'sub_cat_id'))
    return {
        'item_id': item.pk,
        'item_name': item.item_name,
        'unit_name': item.unit.unit_name if item.unit else None,
        'sub_categories': [
            {
                'sub_cat_id': sub_cat.pk,
                'sub_cat_name': sub_cat.sub_cat_name,
                'specs': [spec for spec in specs if spec['sub_cat_id'] == sub_cat.pk],
            }
            for sub_cat in item.sub_categories.filter(is_active=True).order_by('sub_cat_name')
        ],
        'specs': [spec for spec in specs if spec['sub_cat_id'] is None],
    }


# --- Transaction images -----------------------------------------------------

logger = logging.getLogger(__name__)

IMAGE_FIELDS = ('picture', 'receipt')
MAX_UPLOAD_MB = 15
MAX_IMAGE_SIDE = 2000  # pixels; larger photos are scaled down
JPEG_QUALITY = 85


def shrink_image(upload):
    """The uploaded photo as a JPEG of at most MAX_IMAGE_SIDE pixels a side, turned upright."""
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise serializers.ValidationError(f'Images can be at most {MAX_UPLOAD_MB} MB.')
    upload.seek(0)
    with Image.open(upload) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=JPEG_QUALITY, optimize=True)
    return ContentFile(output.getvalue(), name=f'{PurePath(upload.name).stem[:80]}.jpg')


def delete_files(names):
    """
    Removes stored image files; a missing file is fine. A file that can not be removed (e.g. Windows keeps it
    while someone is downloading it) is logged and left behind rather than failing the save.
    """
    storage = InventoryTransaction._meta.get_field('picture').storage
    for name in names:
        if name:
            try:
                storage.delete(name)
            except OSError as error:
                logger.warning('Could not delete %s: %s', name, error)


def editable_copy(data):
    """A copy of request data that can be changed; uploaded files are shared, not copied."""
    if isinstance(data, QueryDict):
        copy = QueryDict(mutable=True)
        for key, values in data.lists():
            copy.setlist(key, values)
        return copy
    return dict(data)


# --- Inventory transactions -------------------------------------------------

SIDES = ('from', 'to')



def side_fields(side):
    """The storage location and shed fields of the sending ('from') or receiving ('to') side."""
    return f'{side}_storage_location', f'{side}_sto_shed'


def sides_used(direction):
    """Sides a transaction of this direction fills; the first is the one a storage location user's own location goes on."""
    return {
        TransactionType.IN: ('to',),
        TransactionType.OUT: ('from',),
        TransactionType.TRANSFER: ('from', 'to'),
        TransactionType.STATUS: ('from', 'to'),
    }[direction]


def stock_keys(txn):
    """
    (storage location, shed, item, sub category, spec, status, owner, condition) of each side the transaction touches.
    The sending side is at the old status and condition (`from_status`, `from_condition`) and of the old owner
    (`from_owner`) when they change.
    """
    keys = set()
    for side in SIDES:
        location_name, shed_name = side_fields(side)
        location_id = getattr(txn, f'{location_name}_id')
        if location_id is not None:
            status_id = txn.from_status_id if side == 'from' and txn.from_status_id else txn.status_id
            owner_id = txn.from_owner_id if side == 'from' and txn.from_owner_id else txn.owner_id
            condition_id = txn.from_condition_id if side == 'from' and txn.from_condition_id else txn.condition_id
            keys.add((location_id, getattr(txn, f'{shed_name}_id'),
                      txn.item_id, txn.sub_cat_id, txn.spec_id, status_id, owner_id, condition_id))
    return keys


def on_hand(location_id, shed_id, item_id, sub_cat_id, spec_id, status_id, owner_id, condition_id):
    """Quantity of one owner and condition at a storage location, or at one of its sheds when `shed_id` is given."""
    rows = InventoryTransaction.objects.filter(item_id=item_id, sub_cat_id=sub_cat_id, spec_id=spec_id) \
        .exclude(approval_status=InventoryTransaction.REJECTED)
    # Received at the row's status and owner once approved; sent (approved or still pending, which holds the stock)
    # at the old status and owner when they change, else at the row's.
    received = Q(to_storage_location_id=location_id, status_id=status_id, owner_id=owner_id, condition_id=condition_id,
                 approval_status=InventoryTransaction.APPROVED)
    sent = Q(from_storage_location_id=location_id) & (
        Q(from_status_id=status_id) | Q(from_status__isnull=True, status_id=status_id)
    ) & (Q(from_owner_id=owner_id) | Q(from_owner__isnull=True, owner_id=owner_id)) & (
        Q(from_condition_id=condition_id) | Q(from_condition__isnull=True, condition_id=condition_id)
    )
    if shed_id is not None:
        received &= Q(to_sto_shed_id=shed_id)
        sent &= Q(from_sto_shed_id=shed_id)

    def total(q):
        return rows.filter(q).aggregate(total=Sum('quantity'))['total'] or 0

    return total(received) - total(sent)


def check_stock(keys):
    """
    Raises a validation error when a save left less than nothing in stock at a storage location or shed.
    Runs after saving, inside the request's database transaction, so the save is rolled back.
    """
    for location_id, shed_id, *item_key in keys:
        for shed in {None, shed_id}:
            quantity = on_hand(location_id, shed, *item_key)
            if quantity < 0:
                place = StorageShed.objects.get(pk=shed) if shed else StorageLocation.objects.get(pk=location_id)
                raise serializers.ValidationError({
                    'quantity': f'Not enough stock at {place.details or place}: this would leave {quantity} '
                                f'of this item, sub category, spec, status, condition and owner.',
                })


def only_condition(status):
    """The condition to fill in when the status has exactly one active condition (Serviceable: Ready to Use)."""
    conditions = list(status.conditions.filter(is_active=True)[:2])
    return conditions[0] if len(conditions) == 1 else None


def add_months(day, months):
    """`day` plus a number of months, kept within the month (31 Jan + 1 month = 28/29 Feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def request_user_is_ndma(serializer):
    request = serializer.context.get('request')
    return request is not None and is_ndma(request.user)


# Issues against demands: warehouse -> warehouse, warehouse -> district, district -> warehouse.
ISSUE_TYPES = (TransactionType.INTERNAL_TRANSFER, TransactionType.DISPATCH, TransactionType.RETURN)

# Types that go to a storage location or out of the system: Dispatch (a district, or a department party) and
# Return (a warehouse, or NDMA for NDMA stock).
OPTIONAL_DESTINATION = (TransactionType.DISPATCH, TransactionType.RETURN)


def movement_kind(from_location, to_location):
    """
    The type of a movement between two storage locations, by their kinds: warehouse to warehouse is Internal
    Transfer (shifting), warehouse to district Dispatch, district to warehouse Return; None for district to district,
    which demands do not do.
    """
    return {
        (False, False): TransactionType.INTERNAL_TRANSFER,
        (False, True): TransactionType.DISPATCH,
        (True, False): TransactionType.RETURN,
    }.get((is_district(from_location), is_district(to_location)))


def needed_approval(txn_type, from_location, to_location, user, demand_issue=False, ndma_handover=False):
    """
    PENDING when a movement waits for approval: status changes (inspection team); warehouse movements, returns,
    district to district dispatches and NDMA stock sent to PDMA (DG PDMA, who chooses the receiving warehouse).
    The DG's own movements, receipts, a district's dispatch to a department, NDMA's other movements of its stock
    and issues against approved demands are APPROVED at once.
    """
    if demand_issue or txn_type.direction == TransactionType.IN:
        return InventoryTransaction.APPROVED
    if txn_type.direction == TransactionType.STATUS:
        return InventoryTransaction.PENDING
    if ndma_handover:
        return InventoryTransaction.PENDING
    if is_ndma(user) or is_master(user):
        return InventoryTransaction.APPROVED
    if txn_type.pk == TransactionType.RETURN:
        return InventoryTransaction.PENDING
    if is_district(from_location):
        return InventoryTransaction.PENDING if to_location is not None else InventoryTransaction.APPROVED
    return InventoryTransaction.PENDING if from_location is not None else InventoryTransaction.APPROVED


def movement_errors(txn_type, from_location, to_location, from_shed, to_shed, party, ndma_handover, sent_owner_id):
    """Where each type may go: {field: message} for a movement that breaks the rules."""
    same_place = to_location is not None and to_location == from_location
    if txn_type.pk == TransactionType.INTERNAL_TRANSFER:
        if is_district(from_location) or is_district(to_location):
            return {'txn_type': 'Internal Transfer (shifting) is only from warehouse to warehouse or shed to shed; '
                                'use Dispatch to send to a district, Return to send back to a warehouse.'}
        if same_place and (None in (from_shed, to_shed) or from_shed == to_shed):
            return {'to_storage_location': 'Choose another warehouse, or another shed of this one.'}
    elif txn_type.pk == TransactionType.DISPATCH:
        if ndma_handover:
            if party is not None or (to_location is not None and is_district(to_location)):
                return {'to_storage_location': 'NDMA stock is dispatched only to PDMA warehouses; the DG PDMA '
                                               'chooses which one.'}
        elif to_location is not None:
            if party is not None:
                return {'party': 'Dispatch to a district or to a department, not both.'}
            if not is_district(to_location):
                return {'to_storage_location': 'Warehouse to warehouse is shifting: use Internal Transfer.'}
            if same_place:
                return {'to_storage_location': 'Choose another district.'}
        elif party is None:
            return {'to_storage_location': 'Choose the district or the department it goes to.'}
    elif txn_type.pk == TransactionType.RETURN:
        if is_district(from_location):
            if to_location is None or is_district(to_location):
                return {'to_storage_location': 'A district returns stock to a warehouse.'}
        elif to_location is not None or sent_owner_id != StockOwner.NDMA:
            return {'to_storage_location': 'PDMA returns only NDMA stock, to NDMA (leave the destination empty, '
                                           'owner 2); districts return to warehouses.'}
    return {}


def item_option_errors(item, sub_cat, spec, require_choice):
    """
    Errors when the sub category or spec is not of the item; with `require_choice` also when the item has
    sub categories or specs to choose from and none is chosen.
    """
    if sub_cat is not None and sub_cat.item_id != item.pk:
        return {'sub_cat': 'This sub category is not of the chosen item.'}
    if spec is not None and (spec.item_id != item.pk or spec.sub_cat_id not in (None, getattr(sub_cat, 'pk', None))):
        return {'spec': 'This spec is not of the chosen item and sub category.'}
    if require_choice:
        if sub_cat is None and item.sub_categories.filter(is_active=True).exists():
            return {'sub_cat': 'Choose a sub category of this item.'}
        if spec is None and specs_for(item.pk, getattr(sub_cat, 'pk', None)).exists():
            return {'spec': 'Choose a spec of this item.'}
    return {}


def check_allocation(txn):
    """
    A transaction issued against a demand allocation must stay a transfer of that line's item from the allocation's
    storage location to the demanding one, and all its issues together may not exceed the approved quantity.
    """
    if txn.demand_allocation_id is None:
        return
    allocation = txn.demand_allocation
    line = allocation.line
    if (txn.txn_type_id not in ISSUE_TYPES
            or (txn.item_id, txn.sub_cat_id, txn.spec_id) != (line.item_id, line.sub_cat_id, line.spec_id)
            or txn.from_storage_location_id != allocation.from_storage_location_id
            or (txn.from_owner_id or txn.owner_id) != allocation.owner_id
            or txn.owner_id != StockOwner.PDMA
            or txn.to_storage_location_id != line.demand.for_storage_location_id):
        raise serializers.ValidationError(
            'An issue against a demand must stay a movement of the demanded item, '
            'from the approved storage location to the demanding one.'
        )
    issued = allocation.transactions.aggregate(total=Sum('quantity'))['total'] or 0
    if issued > allocation.quantity:
        raise serializers.ValidationError({
            'quantity': f'Only {allocation.quantity - (issued - txn.quantity)} more can be issued against this approval '
                        f'({allocation.quantity} approved).',
        })


class InventoryTransactionListSerializer(serializers.ListSerializer):
    """POST a list to save several item lines at once; they are saved together or not at all."""

    def create(self, validated_data):
        with transaction.atomic():
            return [self.child.create(attrs) for attrs in validated_data]


class InventoryTransactionSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    """
    One item line of a donation, procurement, NDMA receipt, dispatch, internal transfer or opening stock.

    Incoming types need `to_storage_location`, Dispatch needs `from_storage_location`, Internal Transfer both.
    Storage location users may leave out their own side (the receiving side of incoming lines, else the sending one).
    A shed may be given instead of its storage location, as a storage shed id or as the shed number there.
    `party` (supplier, donor, NDMA) must be a party of the transaction type; new lines must pick one when the type
    has any. New Dispatch lines need `issued_to`.
    `sub_cat` and `spec` must belong to the item; new lines must pick them when the item has any.
    `status` (Serviceable, Non Serviceable) is required on every new line, with its `condition` (Ready to Use;
    Repairable, Expired, Beyond Repair), filled in when the status has only one. `shelf_life_months` with a
    `manufacturing_date` sets the `expiry_date` when none is given. Stock is kept per status, so a dispatch
    or transfer takes stock of the status it names.
    Dispatch goes to a district (`to_storage_location`; stock moves there) or to a department (`party` of the Dispatch
    type, with a `purpose`; stock leaves the system). Internal Transfer is only warehouse to warehouse or shed to shed.
    Return goes from a district to a warehouse, or from PDMA to NDMA with NDMA stock (no destination). NDMA dispatches
    its stock to PDMA without a warehouse; the DG PDMA chooses it when approving, and it becomes PDMA's stock.
    Warehouse movements, returns and district to district dispatches wait for DG PDMA approval (`approval_status`
    pending) unless the DG records them; status changes wait for the inspection team. Pending movements change no
    stock until approved but already hold the sent quantity. A district's stock is moved only by the district.
    `owner` is whose stock it is (1 PDMA, the default, or 2 NDMA); stock is kept per owner in every storage location.
    Only NDMA users record or move NDMA stock (or hand stock over with `from_owner`); PDMA gets it through demands.
    Status Change lines move stock at one storage location from `from_status` to `status` (e.g. damaged boats from
    Serviceable to Non Serviceable); give `from_storage_location` (storage location users may leave it out) and
    optionally `from_sto_shed` / `to_sto_shed`; the receiving side defaults to the same storage location and shed.
    No save may leave less than nothing in stock.
    `picture` (the goods) and `receipt` are image uploads (multipart/form-data; send an empty value to remove one).
    They are stored as JPEG and come back as URLs of /api/transactions/<id>/picture/ and /receipt/, which need a login.
    """
    txn_type_name = name_field('txn_type.type_name')
    direction = name_field('txn_type.direction')
    item_name = name_field('item.item_name')
    category_name = name_field('item.item_category.category_name')
    unit_name = name_field('item.unit.unit_name')
    sub_cat_name = name_field('sub_cat.sub_cat_name')
    spec_name = name_field('spec.spec_name')
    status_name = name_field('status.status_name')
    from_status_name = name_field('from_status.status_name')
    condition_name = name_field('condition.condition_name')
    from_condition_name = name_field('from_condition.condition_name')
    owner_name = name_field('owner.owner_name')
    from_owner_name = name_field('from_owner.owner_name')
    from_storage_location_name = name_field('from_storage_location.details')
    from_shed_name = name_field('from_sto_shed.shed.shed_name')
    to_storage_location_name = name_field('to_storage_location.details')
    to_shed_name = name_field('to_sto_shed.shed.shed_name')
    party_name = name_field('party.party_name')
    demand_no = name_field('demand_allocation.line.demand.demand_no')
    purpose_name = name_field('purpose.purpose_name')

    # A transfer goes to another storage location, so the receiving side is not limited to the user's own.
    unscoped_fields = ('to_storage_location', 'to_sto_shed')

    class Meta:
        model = InventoryTransaction
        fields = "__all__"
        read_only_fields = ['created_by', 'created_at', 'demand_allocation',
                            'approval_status', 'approved_by', 'approved_at', 'approval_remarks']
        list_serializer_class = InventoryTransactionListSerializer
        # Chosen on every new line (Serviceable, Non Serviceable...); there is no default.
        extra_kwargs = {
            'status': {'required': True, 'allow_null': False},
            'condition': {'required': False},
            'shelf_life_months': {'min_value': 1},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_files = []  # stored by this save; removed again when the save is rolled back
        self.replaced_files = []  # replaced or removed by this save; deleted once it is committed

    def validate_picture(self, value):
        return shrink_image(value) if value else value

    def validate_receipt(self, value):
        return shrink_image(value) if value else value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        for field in IMAGE_FIELDS:
            if getattr(instance, field):
                url = f'/api/transactions/{instance.pk}/{field}/'
                data[field] = request.build_absolute_uri(url) if request is not None else url
            else:
                data[field] = None
        return data

    def own_location_id(self):
        """The storage location user's own storage location; None for master and all areas users."""
        request = self.context.get('request')
        if request is None or sees_all_locations(request.user):
            return None
        return user_location_id(request.user)

    def to_internal_value(self, data):
        """A shed number (Shed id, e.g. 1 for "Shed-1") becomes the storage shed with that shed at the side's storage location."""
        if hasattr(data, 'get'):
            for side in SIDES:
                location_name, shed_name = side_fields(side)
                value = data.get(shed_name)
                if value in (None, ''):
                    continue
                location_id = data.get(location_name)
                if location_id in (None, '') and self.instance is not None:
                    location_id = getattr(self.instance, f'{location_name}_id')
                if location_id in (None, ''):
                    location_id = self.own_location_id()
                sheds = StorageShed.objects.filter(sto_loc_id=location_id)
                try:
                    if location_id is not None and not sheds.filter(pk=value).exists():
                        match = sheds.filter(shed_id=value).values_list('pk', flat=True).first()
                        if match is not None:
                            data = editable_copy(data)
                            data[shed_name] = match
                except (TypeError, ValueError):
                    pass  # not a number; the field reports it
        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance

        def value(name):
            return attrs[name] if name in attrs else getattr(instance, name, None)

        errors = {}
        txn_type = value('txn_type')
        used = sides_used(txn_type.direction)
        if txn_type.pk in OPTIONAL_DESTINATION:
            used = ('from', 'to')  # the receiving side may stay empty (out of the system)
        for side in SIDES:
            location_name, shed_name = side_fields(side)
            location, shed = value(location_name), value(shed_name)
            if side not in used:
                if location is not None or shed is not None:
                    errors[location_name] = f'Not used for {txn_type.type_name}.'
                continue
            if location is None and shed is not None:
                location = attrs[location_name] = shed.sto_loc
            if location is None and side == used[0] and self.own_location_id() is not None:
                location = attrs[location_name] = StorageLocation.objects.get(pk=self.own_location_id())
            if side == 'to' and txn_type.direction == TransactionType.STATUS:
                # A status change stays where it is unless another shed there is given.
                if location is None:
                    location = attrs[location_name] = value('from_storage_location')
                if shed is None and shed_name not in attrs:
                    shed = attrs[shed_name] = value('from_sto_shed')
            if location is None:
                if not (side == 'to' and txn_type.pk in OPTIONAL_DESTINATION):
                    errors[location_name] = 'This field is required.'
            elif shed is not None and shed.sto_loc_id != location.pk:
                errors[shed_name] = 'This shed is not at that storage location.'
        from_location, to_location = value('from_storage_location'), value('to_storage_location')
        request = self.context.get('request')
        user = request.user if request is not None else None
        demand_issue = bool(self.context.get('demand_issue')) or getattr(instance, 'demand_allocation_id', None)
        party = value('party')

        # Whose stock is sent: NDMA users send NDMA stock; a Dispatch of it hands it over to PDMA.
        if instance is None and 'owner' not in attrs and request_user_is_ndma(self):
            attrs['owner'] = StockOwner.objects.get(pk=StockOwner.NDMA)
        if instance is None and txn_type.pk == TransactionType.DISPATCH and request_user_is_ndma(self):
            attrs['from_owner'] = StockOwner.objects.get(pk=StockOwner.NDMA)
            attrs['owner'] = StockOwner.objects.get(pk=StockOwner.PDMA)
        owner, from_owner = value('owner'), value('from_owner')
        sent_owner_id = getattr(from_owner or owner, 'pk', StockOwner.PDMA)
        ndma_handover = txn_type.pk == TransactionType.DISPATCH and sent_owner_id == StockOwner.NDMA
        return_to_ndma = txn_type.pk == TransactionType.RETURN and to_location is None

        if from_location is not None and not errors and not demand_issue:
            errors.update(movement_errors(txn_type, from_location, to_location, value('from_sto_shed'),
                                          value('to_sto_shed'), party, ndma_handover, sent_owner_id))

        # A district's stock is its own: only the district moves it (the DG asks for returns through demands).
        if is_district(from_location) and not demand_issue and request is not None \
                and not (is_ndma(request.user) and sent_owner_id == StockOwner.NDMA) \
                and (sees_all_locations(request.user) or user_location_id(request.user) != from_location.pk):
            errors['from_storage_location'] = ('District stock is managed by the district itself; '
                                               'the DG PDMA requests a return through a demand.')

        # NDMA's stock (in any storage location) is recorded, moved or handed over only by NDMA users, or issued
        # through a demand NDMA approved. `from_owner` is the owner before, when ownership changes hands.
        if from_owner is not None and owner is not None and from_owner == owner:
            errors['from_owner'] = 'Choose a different owner than the new one, or leave it out.'
        request = self.context.get('request')
        ndma_stock = StockOwner.NDMA in {getattr(owner, 'pk', None), getattr(from_owner, 'pk', None)}
        if instance is not None:
            ndma_stock |= StockOwner.NDMA in {instance.owner_id, instance.from_owner_id}
        if ndma_stock and not self.context.get('demand_issue') and not return_to_ndma \
                and not (request and is_ndma(request.user)):
            errors['owner'] = ('Only NDMA records or moves NDMA stock; PDMA gets it through demands or NDMA\'s '
                               'dispatches, and returns it to NDMA with Return.')
        if not ndma_stock and request and is_ndma(request.user):
            errors['owner'] = 'NDMA records only NDMA stock (owner 2).'

        # A status change stays at one storage location (and, unless another is given, in the same shed) and
        # moves stock from `from_status` to `status`.
        # The condition (Ready to Use, Expired, Repairable...) belongs to the status; with only one under the status
        # it is filled in. A status change moves stock from (from_status, from_condition) to (status, condition).
        status = value('status')
        if instance is None and 'condition' not in attrs and status is not None:
            attrs['condition'] = only_condition(status)
        condition = value('condition')
        if condition is None:
            errors['condition'] = f'Choose the condition of the {status.status_name} stock.' if status else 'Required.'
        elif status is not None and condition.status_id != status.pk:
            errors['condition'] = f'Not a condition of {status.status_name}.'
        from_status = value('from_status')
        if txn_type.direction == TransactionType.STATUS:
            if from_status is not None and instance is None and 'from_condition' not in attrs:
                attrs['from_condition'] = only_condition(from_status)
            from_condition = value('from_condition')
            if from_status is None:
                errors['from_status'] = 'Choose the status the stock has now.'
            elif from_condition is None:
                errors['from_condition'] = f'Choose the condition the {from_status.status_name} stock has now.'
            elif from_condition.status_id != from_status.pk:
                errors['from_condition'] = f'Not a condition of {from_status.status_name}.'
            elif (from_status, from_condition) == (status, condition):
                errors['condition'] = 'Choose a different status or condition than the current one.'
            if value('from_storage_location') != value('to_storage_location'):
                errors['to_storage_location'] = 'A status change stays at the same storage location.'
        else:
            if from_status is not None:
                errors['from_status'] = f'Not used for {txn_type.type_name}.'
            if value('from_condition') is not None:
                errors['from_condition'] = f'Not used for {txn_type.type_name}.'

        # Shelf life in months from manufacturing sets the expiry date when none is given.
        # Checked only when the dates are entered or changed, so older records with odd dates can still be edited.
        if instance is None or {'manufacturing_date', 'expiry_date', 'shelf_life_months'} & set(attrs):
            manufactured, expiry = value('manufacturing_date'), value('expiry_date')
            if value('shelf_life_months') and manufactured and not expiry:
                expiry = attrs['expiry_date'] = add_months(manufactured, value('shelf_life_months'))
            if manufactured and expiry and expiry < manufactured:
                errors['expiry_date'] = 'The expiry date is before the manufacturing date.'

        # The supplier, donor, NDMA or receiving department must be one of the transaction type's parties; new
        # receipts must pick one when the type has any (a Dispatch picks a district or a department instead).
        if party is not None and party.txn_type_id != txn_type.pk:
            errors['party'] = f'Not a party of {txn_type.type_name}.'
        if instance is None and party is None and txn_type.direction == TransactionType.IN \
                and txn_type.parties.filter(is_active=True).exists():
            errors['party'] = f'Choose the {txn_type.type_name} party.'
        if instance is None and txn_type.pk == TransactionType.DISPATCH and party is not None \
                and value('purpose') is None:
            errors['purpose'] = 'Choose the purpose of the dispatch.'
        if value('purpose') is not None and txn_type.pk != TransactionType.DISPATCH:
            errors['purpose'] = f'Not used for {txn_type.type_name}.'

        # Whether it waits for approval; a change to a movement that needs approval needs it again.
        if not errors and request is not None:
            attrs['approval_status'] = needed_approval(txn_type, from_location, to_location, request.user,
                                                       demand_issue, ndma_handover)
            if attrs['approval_status'] == InventoryTransaction.PENDING:
                attrs['approved_by'] = attrs['approved_at'] = None

        if not errors:
            errors.update(item_option_errors(value('item'), value('sub_cat'), value('spec'), instance is None))
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        txn = super().create(validated_data)
        self.new_files += [getattr(txn, field).name for field in IMAGE_FIELDS if validated_data.get(field)]
        check_stock(stock_keys(txn))
        check_allocation(txn)
        return txn

    def update(self, instance, validated_data):
        before = stock_keys(instance)
        old_files = {field: getattr(instance, field).name for field in IMAGE_FIELDS}
        txn = super().update(instance, validated_data)
        for field in IMAGE_FIELDS:
            if field in validated_data:
                if validated_data[field]:
                    self.new_files.append(getattr(txn, field).name)
                self.replaced_files.append(old_files[field])
        check_stock(before | stock_keys(txn))
        check_allocation(txn)
        return txn


