import json

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Categories,
    Donation,
    Donors,
    GoodsReceipt,
    ItemStatus,
    Items,
    Locations,
    PurchaseOrder,
    Shed,
    StorageLocation,
    StorageShed,
    StorageType,
    Stock,
    StockTransaction,
    Suppliers,
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


class DonorsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donors
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


class SuppliersSerializer(serializers.ModelSerializer):
    class Meta:
        model = Suppliers
        fields = "__all__"


class UnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Units
        fields = "__all__"


class ItemsSerializer(serializers.ModelSerializer):
    item_category = CategoriesSerializer(read_only=True)

    class Meta:
        model = Items
        fields = "__all__"


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


class StockSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    item_name = name_field('item.item_name')
    storage_location_name = name_field('location.sto_loc.details')
    location_name = name_field('location.sto_loc.location.location_name')
    shed_name = name_field('location.shed.shed_name')
    status_name = name_field('status.status_name')

    class Meta:
        model = Stock
        fields = "__all__"


class StockTransactionSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = StockTransaction
        fields = "__all__"


class TotalInventorySerializer(serializers.Serializer):
    """Read-only serializer for aggregated total inventory per item."""
    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    item_code = serializers.CharField(allow_null=True)
    category_name = serializers.CharField(allow_null=True)
    total_quantity = serializers.DecimalField(max_digits=15, decimal_places=2)
    unit = serializers.CharField()
    stock_entries = serializers.IntegerField()


# --- Records with JSON line details -----------------------------------------

class JSONDetailsMixin(serializers.Serializer):
    """
    Stores the `details` list as JSON text on the record itself.
    Missing item and `detail_fields` values are taken from the first line.
    """
    details = serializers.JSONField(required=False, allow_null=True)
    detail_fields = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # details is stored as JSON text; return it as real JSON
        if isinstance(data.get('details'), str):
            try:
                data['details'] = json.loads(data['details'])
            except ValueError:
                pass
        return data

    def _pack_details(self, validated_data):
        """Store details as JSON text and, if missing, take item and detail_fields from its first line."""
        details = validated_data.pop('details', None)
        if details is None:
            return
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                pass

        if isinstance(details, list) and details and isinstance(details[0], dict):
            first = details[0]
            if validated_data.get('item') is None:
                item_id = first.get('item_id') or first.get('item')
                if item_id is not None:
                    validated_data.pop('item', None)
                    validated_data['item_id'] = item_id
            for key in self.detail_fields:
                if validated_data.get(key) is None and key in first:
                    validated_data[key] = first[key]

        validated_data['details'] = json.dumps(details)

    def create(self, validated_data):
        self._pack_details(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._pack_details(validated_data)
        return super().update(instance, validated_data)


class OwnStorageLocationMixin:
    """
    New records without `storage_location` get the user's own storage location.
    Master and all areas users have to choose one.
    """

    def get_fields(self):
        fields = super().get_fields()
        fields['storage_location'].required = False
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None and attrs.get('storage_location') is None:
            request = self.context.get('request')
            user = request.user if request is not None else None
            profile = getattr(user, 'profile', None)
            if user is None or sees_all_locations(user) or profile is None or profile.storage_location is None:
                raise serializers.ValidationError({'storage_location': 'This field is required.'})
            attrs['storage_location'] = profile.storage_location
        return attrs


class ShedNumberMixin:
    """
    `sto_shed` also accepts a shed number (Shed id, e.g. 1 for "Shed-1"): it becomes the storage shed with
    that shed at the record's storage location. Ids of that storage location's storage sheds are kept as is.
    The record's storage location comes from `storage_location_id_from`, else the user's own.
    """

    def storage_location_id_from(self, data):
        if data.get('storage_location') not in (None, ''):
            return data['storage_location']
        return self.instance.storage_location_id if self.instance is not None else None

    def to_internal_value(self, data):
        value = data.get('sto_shed') if hasattr(data, 'get') else None
        if value not in (None, ''):
            request = self.context.get('request')
            location_id = self.storage_location_id_from(data)
            if location_id is None and request is not None:
                location_id = user_location_id(request.user)
            sheds = StorageShed.objects.filter(sto_loc_id=location_id)
            try:
                if location_id is not None and not sheds.filter(pk=value).exists():
                    match = sheds.filter(shed_id=value).values_list('pk', flat=True).first()
                    if match is not None:
                        data = data.copy()
                        data['sto_shed'] = match
            except (TypeError, ValueError):
                pass  # not a number; the field reports it
        return super().to_internal_value(data)


# --- Purchase order --------------------------------------------------------

class PurchaseOrderSerializer(OwnStorageLocationMixin, ShedNumberMixin, LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    storage_location_name = name_field('storage_location.details')
    location_name = name_field('storage_location.location.location_name')
    supplier_name = name_field('supplier.supplier_name')
    item_name = name_field('item.item_name')
    detail_fields = ('quantity', 'unit_price')

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ['created_by', 'created_at']
        extra_kwargs = {
            'item': {'required': False},
            'quantity': {'required': False},
            'unit_price': {'required': False},
        }


# --- Goods receipt ---------------------------------------------------------

class GoodsReceiptSerializer(ShedNumberMixin, LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    po_id = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrder.objects.all(), source='po')
    po_number = name_field('po.po_number')
    supplier_name = name_field('po.supplier.supplier_name')
    item_name = name_field('item.item_name')
    detail_fields = ('received_quantity', 'unit_cost', 'batch_no', 'manufacturing_date', 'expiry_date')

    def storage_location_id_from(self, data):
        """A goods receipt is stored at its purchase order's storage location."""
        if data.get('po_id') not in (None, ''):
            try:
                return PurchaseOrder.objects.filter(pk=data['po_id']).values_list('storage_location_id', flat=True).first()
            except (TypeError, ValueError):
                return None
        return self.instance.po.storage_location_id if self.instance is not None else None

    class Meta:
        model = GoodsReceipt
        exclude = ['po']
        read_only_fields = ['received_by']
        extra_kwargs = {
            'item': {'required': False},
            'received_quantity': {'required': False},
        }


# --- Donation --------------------------------------------------------------

class DonationSerializer(OwnStorageLocationMixin, ShedNumberMixin, LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    donor_name = name_field('donor.donor_name')
    storage_location_name = name_field('storage_location.details')
    location_name = name_field('storage_location.location.location_name')
    item_name = name_field('item.item_name')
    detail_fields = ('quantity', 'estimated_unit_value', 'batch_no', 'manufacturing_date', 'expiry_date')

    class Meta:
        model = Donation
        fields = "__all__"
        read_only_fields = ['created_by', 'created_at']
        extra_kwargs = {
            'item': {'required': False},
            'quantity': {'required': False},
        }
