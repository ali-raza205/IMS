import json
import logging

import mimetypes

from django.db import transaction
from django.http import FileResponse, Http404
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

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
    InventoryTransactionSerializer,
    ItemSpecSerializer,
    ItemStatusSerializer,
    ItemSubCategorySerializer,
    ItemsSerializer,
    LocationsSerializer,
    LoginSerializer,
    PartySerializer,
    ShedSerializer,
    StockBalanceSerializer,
    StorageTypeSerializer,
    StorageLocationSerializer,
    StorageShedSerializer,
    TotalInventorySerializer,
    TransactionTypeSerializer,
    UnitsSerializer,
    check_stock,
    delete_files,
    item_options,
    specs_for,
    stock_keys,
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


class UnitsViewSet(MasterDataViewSet):
    queryset = Units.objects.all()
    serializer_class = UnitsSerializer


class ItemStatusViewSet(MasterDataViewSet):
    queryset = ItemStatus.objects.all()
    serializer_class = ItemStatusSerializer


def id_param(request, name):
    """The `?<name>=<id>` filter, or None."""
    value = request.query_params.get(name)
    return int(value) if value and value.isdigit() else None


def storage_location_param(request):
    """The `?storage_location=<id>` filter, or None."""
    return id_param(request, 'storage_location')


class ItemsViewSet(MasterDataViewSet):
    """
    GET /api/items/?item_category=<id> filters by category; POST accepts the same param to set it.
    GET /api/items/<id>/options/ returns the item's sub categories with their specs, for the item form dropdowns.
    """
    queryset = Items.objects.select_related('item_category', 'unit').order_by('item_name')
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

    @action(detail=True)
    def options(self, request, pk=None):
        return Response(item_options(self.get_object()))


class ItemSubCategoryViewSet(MasterDataViewSet):
    """GET /api/item-sub-category/?item=<id> lists the sub categories of an item."""
    queryset = ItemSubCategory.objects.select_related('item').order_by('sub_cat_name')
    serializer_class = ItemSubCategorySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        item_id = id_param(self.request, 'item')
        if item_id is not None:
            queryset = queryset.filter(item_id=item_id)
        if self.action == 'list' and self.request.query_params.get('include_inactive') != 'true':
            queryset = queryset.filter(is_active=True)
        return queryset


class ItemSpecViewSet(MasterDataViewSet):
    """
    GET /api/item-spec/?item=<id>&sub_category=<id> lists the specs to choose from for that item and sub category:
    the sub category's own specs plus those of the whole item. Without `sub_category` only the whole item's specs.
    """
    queryset = ItemSpec.objects.select_related('item', 'sub_cat').order_by('spec_name')
    serializer_class = ItemSpecSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        item_id = id_param(self.request, 'item')
        if item_id is not None:
            queryset = queryset.filter(pk__in=specs_for(item_id, id_param(self.request, 'sub_category')))
        if self.action == 'list' and self.request.query_params.get('include_inactive') != 'true':
            queryset = queryset.filter(is_active=True)
        return queryset


class TransactionTypeViewSet(LogSubmitMixin, viewsets.ModelViewSet):
    """Donation, Procurement, NDMA, Dispatch, Internal Transfer, Opening Stock; only master users change them."""
    queryset = TransactionType.objects.order_by('type_id')
    serializer_class = TransactionTypeSerializer
    permission_classes = [IsAuthenticated, IsMasterOrReadOnly]


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


class PartyViewSet(MasterDataViewSet):
    """
    Suppliers, donors and NDMA in one list, each under its transaction type.
    GET /api/parties/?txn_type=<id> lists the parties to choose from for that transaction type.
    """
    queryset = Party.objects.select_related('txn_type').order_by('party_name')
    serializer_class = PartySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        txn_type_id = id_param(self.request, 'txn_type')
        if txn_type_id is not None:
            queryset = queryset.filter(txn_type_id=txn_type_id)
        if self.action == 'list' and self.request.query_params.get('include_inactive') != 'true':
            queryset = queryset.filter(is_active=True)
        return queryset


# --- Storage location data: location users only see and change their own storage location ---

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


def filter_by_params(queryset, request, filters):
    """Applies `?<param>=<id>` filters given as {param: lookup}."""
    for param, lookup in filters.items():
        value = id_param(request, param)
        if value is not None:
            queryset = queryset.filter(**{lookup: value})
    return queryset


class InventoryTransactionViewSet(LogSubmitMixin, LocationScopedMixin, viewsets.ModelViewSet):
    """
    All incoming and outgoing stock movements. POST one line, or a list of lines that are saved together.
    Both the sending and the receiving storage location see a transaction; a storage location user changes only
    lines sent from their storage location, or received there from outside (donation, procurement, NDMA...).
    Filters: ?txn_type, ?direction (in/out/transfer), ?party, ?item, ?sub_category, ?spec, ?status, ?storage_location,
    ?date_from and ?date_to (YYYY-MM-DD).
    """
    queryset = InventoryTransaction.objects.select_related(
        'txn_type', 'item__item_category', 'item__unit', 'sub_cat', 'spec', 'status', 'party',
        'from_storage_location', 'from_sto_shed__shed', 'to_storage_location', 'to_sto_shed__shed',
    ).order_by('-txn_date', '-txn_id')
    serializer_class = InventoryTransactionSerializer
    created_by_field = 'created_by'

    def write_filter(self, location_id):
        return Q(from_storage_location=location_id) | Q(from_storage_location__isnull=True, to_storage_location=location_id)

    def get_queryset(self):
        queryset = filter_by_params(super().get_queryset(), self.request, {
            'txn_type': 'txn_type', 'party': 'party', 'item': 'item', 'sub_category': 'sub_cat', 'spec': 'spec',
            'status': 'status',
        })
        params = self.request.query_params
        if params.get('direction'):
            queryset = queryset.filter(txn_type__direction=params['direction'])
        location_id = storage_location_param(self.request)
        if location_id is not None:
            queryset = queryset.filter(Q(from_storage_location=location_id) | Q(to_storage_location=location_id))
        if params.get('date_from'):
            queryset = queryset.filter(txn_date__gte=params['date_from'])
        if params.get('date_to'):
            queryset = queryset.filter(txn_date__lte=params['date_to'])
        return queryset

    def get_serializer(self, *args, **kwargs):
        if isinstance(kwargs.get('data'), list):
            kwargs['many'] = True
        return super().get_serializer(*args, **kwargs)

    def _save_with_images(self, save, serializer):
        """Saves; uploaded images are removed if the save fails, replaced ones deleted once it is committed."""
        child = getattr(serializer, 'child', serializer)
        try:
            with transaction.atomic():
                save(serializer)
                transaction.on_commit(lambda: delete_files(child.replaced_files))
        except Exception:
            delete_files(child.new_files)
            raise

    def perform_create(self, serializer):
        self._save_with_images(super().perform_create, serializer)

    def perform_update(self, serializer):
        self._save_with_images(super().perform_update, serializer)

    def perform_destroy(self, instance):
        with transaction.atomic():
            keys = stock_keys(instance)
            files = [instance.picture.name, instance.receipt.name]
            super().perform_destroy(instance)
            check_stock(keys)
            transaction.on_commit(lambda: delete_files(files))

    def _image(self, field):
        image = getattr(self.get_object(), field)
        if not image or not image.storage.exists(image.name):
            raise Http404(f'This transaction has no {field}.')
        content_type = mimetypes.guess_type(image.name)[0] or 'application/octet-stream'
        return FileResponse(image.open('rb'), content_type=content_type)

    @action(detail=True)
    def picture(self, request, pk=None):
        """The picture of the goods (needs a login, like the transaction itself)."""
        return self._image('picture')

    @action(detail=True)
    def receipt(self, request, pk=None):
        """The receipt image (needs a login, like the transaction itself)."""
        return self._image('receipt')


class StockViewSet(LocationScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    Quantity on hand per storage location, shed, item, sub category, spec and status (read-only; add transactions
    to change it). Filters: ?storage_location, ?shed (storage shed id), ?item, ?sub_category, ?spec, ?status, ?category.
    """
    queryset = StockBalance.objects.select_related(
        'storage_location__location', 'sto_shed__shed', 'item__item_category', 'item__unit', 'sub_cat', 'spec', 'status',
    ).order_by('storage_location', 'item__item_name', 'row_id')
    serializer_class = StockBalanceSerializer

    def get_queryset(self):
        return filter_by_params(super().get_queryset(), self.request, {
            'storage_location': 'storage_location', 'shed': 'sto_shed', 'item': 'item', 'sub_category': 'sub_cat',
            'spec': 'spec', 'status': 'status', 'category': 'item__item_category',
        })


class TotalInventoryViewSet(viewsets.ViewSet):
    """
    Read-only total stock per item, sub category, spec and status (only the user's own storage location unless master).
    GET /api/total-inventory/ (filters: ?storage_location, ?item, ?category, ?status)
    """
    def list(self, request):
        stock = filter_by_params(limit_to_location(StockBalance.objects.all(), request.user), request, {
            'storage_location': 'storage_location', 'item': 'item', 'category': 'item__item_category', 'status': 'status',
        })
        inventory = (
            stock.values(
                'item_id', 'sub_cat_id', 'spec_id', 'status_id',
                item_name=F('item__item_name'),
                item_code=F('item__item_code'),
                category_name=F('item__item_category__category_name'),
                sub_cat_name=F('sub_cat__sub_cat_name'),
                spec_name=F('spec__spec_name'),
                status_name=F('status__status_name'),
                unit=F('item__unit__unit_name'),
            )
            .annotate(total_quantity=Sum('quantity'), stock_entries=Count('row_id'))
            .order_by('-total_quantity')
        )
        return Response(TotalInventorySerializer(inventory, many=True).data)
