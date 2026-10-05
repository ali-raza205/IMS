import json
import logging

from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

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
from .permissions import (
    IsMasterOrCreateOnly,
    IsMasterOrReadOnly,
    LocationScopedMixin,
    limit_to_location,
    sees_all_locations,
    user_location_id,
)
from .serializers import (
    CategoriesSerializer,
    DonationSerializer,
    DonorsSerializer,
    GoodsReceiptSerializer,
    ItemStatusSerializer,
    ItemsSerializer,
    LocationsSerializer,
    LoginSerializer,
    PurchaseOrderSerializer,
    ShedSerializer,
    StorageTypeSerializer,
    StorageLocationSerializer,
    StorageShedSerializer,
    StockSerializer,
    StockTransactionSerializer,
    SuppliersSerializer,
    TotalInventorySerializer,
    UnitsSerializer,
    user_info,
)


# --- Auth ------------------------------------------------------------------

class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/ with {"username", "password"}.
    Returns {"access", "refresh", "user"}; send "Authorization: Bearer <access>" on other calls.
    """
    serializer_class = LoginSerializer


class MeView(APIView):
    """GET /api/auth/me/ returns the logged-in user's role and storage location."""

    def get(self, request):
        return Response(user_info(request.user))


# --- Shared master data: everyone reads and adds, only master users edit or delete ---

logger = logging.getLogger('db.submit')


class LogSubmitMixin:
    """Prints every submit (add, edit, delete) to the server console before it is validated and saved."""

    def initial(self, request, *args, **kwargs):
        if request.method not in SAFE_METHODS:
            data = request.data.dict() if hasattr(request.data, 'dict') else request.data
            logger.info('%s %s by %s: %s', request.method, request.get_full_path(), request.user,
                        json.dumps(data, default=str, ensure_ascii=False))
        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        if request.method not in SAFE_METHODS and response.status_code >= 400:
            logger.warning('%s %s rejected (%s): %s', request.method, request.get_full_path(),
                           response.status_code, json.dumps(response.data, default=str, ensure_ascii=False))
        return super().finalize_response(request, response, *args, **kwargs)


class MasterDataViewSet(LogSubmitMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsMasterOrCreateOnly]


class CategoriesViewSet(MasterDataViewSet):
    queryset = Categories.objects.all()
    serializer_class = CategoriesSerializer


class DonorsViewSet(MasterDataViewSet):
    queryset = Donors.objects.all()
    serializer_class = DonorsSerializer


class SuppliersViewSet(MasterDataViewSet):
    queryset = Suppliers.objects.all()
    serializer_class = SuppliersSerializer


class UnitsViewSet(MasterDataViewSet):
    queryset = Units.objects.all()
    serializer_class = UnitsSerializer


class ItemStatusViewSet(MasterDataViewSet):
    queryset = ItemStatus.objects.all()
    serializer_class = ItemStatusSerializer


class ItemsViewSet(MasterDataViewSet):
    """GET /api/items/?item_category=<id> filters by category; POST accepts the same param to set it."""
    queryset = Items.objects.select_related('item_category')
    serializer_class = ItemsSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get('item_category')
        if category_id:
            queryset = queryset.filter(item_category=category_id)
        return queryset

    def perform_create(self, serializer):
        category_id = self.request.query_params.get('item_category')
        if category_id:
            serializer.save(item_category=get_object_or_404(Categories, pk=category_id))
        else:
            serializer.save()


def storage_location_param(request):
    """The `?storage_location=<id>` filter, or None."""
    value = request.query_params.get('storage_location')
    return int(value) if value and value.isdigit() else None


class ShedViewSet(MasterDataViewSet):
    """
    Only sheds that exist at a storage location: the user's own, or `?storage_location=<id>`.
    Master and all areas users see every shed when no storage location is given.
    """
    queryset = Shed.objects.all()
    serializer_class = ShedSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        location_id = storage_location_param(self.request)
        if not sees_all_locations(user):
            own = user_location_id(user)
            if location_id is not None and location_id != own:
                return queryset.none()
            location_id = own
            if location_id is None:
                return queryset.none()
        if location_id is not None:
            queryset = queryset.filter(storageshed__sto_loc_id=location_id).distinct()
        return queryset


class StorageTypeViewSet(MasterDataViewSet):
    queryset = StorageType.objects.all()
    serializer_class = StorageTypeSerializer


class LocationsViewSet(LogSubmitMixin, viewsets.ModelViewSet):
    """Areas (districts) warehouses are established in. Everyone sees all; only master users change them."""
    queryset = Locations.objects.all()
    serializer_class = LocationsSerializer
    permission_classes = [IsAuthenticated, IsMasterOrReadOnly]


class StorageLocationViewSet(LogSubmitMixin, viewsets.ModelViewSet):
    """Everyone sees all storage locations (e.g. to pick a transfer destination); only master users change them."""
    queryset = StorageLocation.objects.select_related('location', 'type')
    serializer_class = StorageLocationSerializer
    permission_classes = [IsAuthenticated, IsMasterOrReadOnly]


# --- Storage location data: location users only see and change their own storage location ---

class DonationViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    queryset = Donation.objects.select_related('donor', 'storage_location__location', 'item')
    serializer_class = DonationSerializer
    created_by_field = 'created_by'


class PurchaseOrderViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related('storage_location__location', 'supplier', 'item')
    serializer_class = PurchaseOrderSerializer
    created_by_field = 'created_by'


class GoodsReceiptViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    queryset = GoodsReceipt.objects.select_related('po__supplier', 'item')
    serializer_class = GoodsReceiptSerializer
    created_by_field = 'received_by'


class StorageShedViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    """GET /api/storage-shed/?storage_location=<id> lists only that storage location's sheds."""
    queryset = StorageShed.objects.select_related('sto_loc__location', 'shed')
    serializer_class = StorageShedSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        location_id = storage_location_param(self.request)
        if location_id is not None:
            queryset = queryset.filter(sto_loc_id=location_id)
        return queryset


class StockViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    queryset = Stock.objects.select_related(
        'item', 'status', 'location__shed', 'location__sto_loc__location'
    )
    serializer_class = StockSerializer


class StockTransactionViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    """Sending and receiving storage locations both see a transfer; only the sender creates or changes it."""
    queryset = StockTransaction.objects.all()
    serializer_class = StockTransactionSerializer

    def scope_filter(self, location_id):
        return Q(from_warehouse=location_id) | Q(to_warehouse=location_id)

    def write_filter(self, location_id):
        return Q(from_warehouse=location_id)


class TotalInventoryViewSet(viewsets.ViewSet):
    """
    Read-only total stock per item (only the user's own storage location unless master).
    GET /api/total-inventory/
    """
    def list(self, request):
        inventory = (
            limit_to_location(Stock.objects.all(), request.user)
            .values(
                'item_id', 'unit',
                item_name=F('item__item_name'),
                item_code=F('item__item_code'),
                category_name=F('item__item_category__category_name'),
            )
            .annotate(total_quantity=Sum('quantity'), stock_entries=Count('stock_id'))
            .order_by('-total_quantity')
        )
        return Response(TotalInventorySerializer(inventory, many=True).data)
