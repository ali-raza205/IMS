from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
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
    """GET /api/auth/me/ returns the logged-in user's role and location."""

    def get(self, request):
        return Response(user_info(request.user))


# --- Shared master data: everyone reads and adds, only master users edit or delete ---

class MasterDataViewSet(viewsets.ModelViewSet):
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


class ShedViewSet(MasterDataViewSet):
    queryset = Shed.objects.all()
    serializer_class = ShedSerializer


class StorageTypeViewSet(MasterDataViewSet):
    queryset = StorageType.objects.all()
    serializer_class = StorageTypeSerializer


class LocationsViewSet(viewsets.ModelViewSet):
    """Everyone sees all locations (e.g. to pick a transfer destination); only master users change them."""
    queryset = Locations.objects.all()
    serializer_class = LocationsSerializer
    permission_classes = [IsAuthenticated, IsMasterOrReadOnly]


# --- Location data: location users only see and change their own location ---

class DonationViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = Donation.objects.select_related('donor', 'warehouse', 'item')
    serializer_class = DonationSerializer
    created_by_field = 'created_by'


class PurchaseOrderViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related('location', 'supplier', 'item')
    serializer_class = PurchaseOrderSerializer
    created_by_field = 'created_by'


class GoodsReceiptViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = GoodsReceipt.objects.select_related('po__supplier', 'item')
    serializer_class = GoodsReceiptSerializer
    created_by_field = 'received_by'


class StorageLocationViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = StorageLocation.objects.select_related('location', 'type')
    serializer_class = StorageLocationSerializer


class StorageShedViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = StorageShed.objects.select_related('sto_loc__location', 'shed')
    serializer_class = StorageShedSerializer


class StockViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    queryset = Stock.objects.select_related(
        'item', 'status', 'location__shed', 'location__sto_loc__location'
    )
    serializer_class = StockSerializer


class StockTransactionViewSet(LocationScopedMixin, viewsets.ModelViewSet):
    """Sending and receiving locations both see a transfer; only the sender creates or changes it."""
    queryset = StockTransaction.objects.all()
    serializer_class = StockTransactionSerializer

    def scope_filter(self, location_id):
        return Q(from_warehouse=location_id) | Q(to_warehouse=location_id)

    def write_filter(self, location_id):
        return Q(from_warehouse=location_id)


class TotalInventoryViewSet(viewsets.ViewSet):
    """
    Read-only total stock per item (only the user's own location unless master).
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
