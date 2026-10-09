from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Categories,
    InventoryTransaction,
    ItemSpec,
    ItemStatus,
    ItemSubCategory,
    Items,
    Locations,
    Party,
    Shed,
    StockBalance,
    StorageLocation,
    StorageShed,
    StorageType,
    TransactionType,
    Units,
    UserProfile,
)
from .permissions import LocationScopedFieldsMixin, is_master, sees_all_locations, user_location_id


def name_field(source):
    """Read-only field that shows a related record's name next to its id."""
    return serializers.CharField(source=source, read_only=True, allow_null=True)


# --- Auth ------------------------------------------------------------------

def user_info(user):
    """Who is logged in, their role and which storage location they are limited to (none for master and all areas users)."""
    profile = getattr(user, 'profile', None)
    storage_location = profile.storage_location if profile else None
    location = storage_location.location if storage_location else None
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.get_full_name(),
        'role': UserProfile.ROLE_MASTER if is_master(user) else (profile.role if profile else UserProfile.ROLE_LOCATION),
        'storage_location_id': storage_location.st_loc_id if storage_location else None,
        'storage_location_name': storage_location.details if storage_location else None,
        'location_id': location.location_id if location else None,
        'location_name': location.location_name if location else None,
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


class UnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Units
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
    }[direction]


def stock_keys(txn):
    """(storage location, shed, item, sub category, spec, status) of each side the transaction touches."""
    keys = set()
    for side in SIDES:
        location_name, shed_name = side_fields(side)
        location_id = getattr(txn, f'{location_name}_id')
        if location_id is not None:
            keys.add((location_id, getattr(txn, f'{shed_name}_id'),
                      txn.item_id, txn.sub_cat_id, txn.spec_id, txn.status_id))
    return keys


def on_hand(location_id, shed_id, item_id, sub_cat_id, spec_id, status_id):
    """Quantity at a storage location, or at one of its sheds when `shed_id` is given."""
    rows = InventoryTransaction.objects.filter(item_id=item_id, sub_cat_id=sub_cat_id, spec_id=spec_id, status_id=status_id)
    received, sent = Q(to_storage_location_id=location_id), Q(from_storage_location_id=location_id)
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
                                f'of this item, sub category, spec and status.',
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
    No save may leave less than nothing in stock.
    """
    txn_type_name = name_field('txn_type.type_name')
    direction = name_field('txn_type.direction')
    item_name = name_field('item.item_name')
    category_name = name_field('item.item_category.category_name')
    unit_name = name_field('item.unit.unit_name')
    sub_cat_name = name_field('sub_cat.sub_cat_name')
    spec_name = name_field('spec.spec_name')
    status_name = name_field('status.status_name')
    from_storage_location_name = name_field('from_storage_location.details')
    from_shed_name = name_field('from_sto_shed.shed.shed_name')
    to_storage_location_name = name_field('to_storage_location.details')
    to_shed_name = name_field('to_sto_shed.shed.shed_name')
    party_name = name_field('party.party_name')

    # A transfer goes to another storage location, so the receiving side is not limited to the user's own.
    unscoped_fields = ('to_storage_location', 'to_sto_shed')

    class Meta:
        model = InventoryTransaction
        fields = "__all__"
        read_only_fields = ['created_by', 'created_at']
        list_serializer_class = InventoryTransactionListSerializer
        extra_kwargs = {'status': {'required': False}}

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
                            data = data.copy()
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
            if location is None:
                errors[location_name] = 'This field is required.'
            elif shed is not None and shed.sto_loc_id != location.pk:
                errors[shed_name] = 'This shed is not at that storage location.'
        if len(used) == 2 and value('from_storage_location') is not None \
                and value('from_storage_location') == value('to_storage_location'):
            errors['to_storage_location'] = 'Must be a different storage location.'

        # The supplier, donor or NDMA must be one of the transaction type's parties; new lines must pick one
        # when the type has any. A dispatch records who received it.
        party = value('party')
        if party is not None and party.txn_type_id != txn_type.pk:
            errors['party'] = f'Not a party of {txn_type.type_name}.'
        if instance is None:
            if party is None and txn_type.parties.filter(is_active=True).exists():
                errors['party'] = f'Choose the {txn_type.type_name} party.'
            if txn_type.pk == TransactionType.DISPATCH and not value('issued_to'):
                errors['issued_to'] = 'Required for Dispatch.'

        item, sub_cat, spec = value('item'), value('sub_cat'), value('spec')
        if sub_cat is not None and sub_cat.item_id != item.pk:
            errors['sub_cat'] = 'This sub category is not of the chosen item.'
        if spec is not None and (spec.item_id != item.pk or spec.sub_cat_id not in (None, getattr(sub_cat, 'pk', None))):
            errors['spec'] = 'This spec is not of the chosen item and sub category.'
        if instance is None and not errors:
            if sub_cat is None and item.sub_categories.filter(is_active=True).exists():
                errors['sub_cat'] = 'Choose a sub category of this item.'
            elif spec is None and specs_for(item.pk, getattr(sub_cat, 'pk', None)).exists():
                errors['spec'] = 'Choose a spec of this item.'
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        txn = super().create(validated_data)
        check_stock(stock_keys(txn))
        return txn

    def update(self, instance, validated_data):
        before = stock_keys(instance)
        txn = super().update(instance, validated_data)
        check_stock(before | stock_keys(txn))
        return txn


