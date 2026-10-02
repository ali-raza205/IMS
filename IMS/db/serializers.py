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
)
from .permissions import LocationScopedFieldsMixin, is_master


def name_field(source):
    """Read-only field that shows a related record's name next to its id."""
    return serializers.CharField(source=source, read_only=True, allow_null=True)


# --- Auth ------------------------------------------------------------------

def user_info(user):
    """Who is logged in and which location they are limited to (none for master users)."""
    profile = getattr(user, 'profile', None)
    location = profile.location if profile else None
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.get_full_name(),
        'role': 'master' if is_master(user) else 'location',
        'location_id': location.location_id if location else None,
        'location_name': location.location_name if location else None,
    }


class LoginSerializer(TokenObtainPairSerializer):
    """Returns the access/refresh tokens plus the user's role and location."""

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

class StorageLocationSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    location_name = name_field('location.location_name')
    type_name = name_field('type.type_name')

    class Meta:
        model = StorageLocation
        fields = "__all__"


class StorageShedSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    location_name = name_field('sto_loc.location.location_name')
    shed_name = name_field('shed.shed_name')

    class Meta:
        model = StorageShed
        fields = "__all__"


class StockSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    item_name = name_field('item.item_name')
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


# --- Purchase order --------------------------------------------------------

class PurchaseOrderSerializer(LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    location_name = name_field('location.location_name')
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

class GoodsReceiptSerializer(LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    po_id = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrder.objects.all(), source='po')
    po_number = name_field('po.po_number')
    supplier_name = name_field('po.supplier.supplier_name')
    item_name = name_field('item.item_name')
    detail_fields = ('received_quantity', 'unit_cost', 'batch_no', 'manufacturing_date', 'expiry_date')

    class Meta:
        model = GoodsReceipt
        exclude = ['po']
        read_only_fields = ['received_by']
        extra_kwargs = {
            'item': {'required': False},
            'received_quantity': {'required': False},
        }


# --- Donation --------------------------------------------------------------

class DonationSerializer(LocationScopedFieldsMixin, JSONDetailsMixin, serializers.ModelSerializer):
    donor_name = name_field('donor.donor_name')
    warehouse_name = name_field('warehouse.location_name')
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
