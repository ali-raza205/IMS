from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    CategoriesViewSet,
    DonationViewSet,
    DonorsViewSet,
    GoodsReceiptViewSet,
    ItemStatusViewSet,
    ItemsViewSet,
    LocationsViewSet,
    LoginView,
    MeView,
    PurchaseOrderViewSet,
    ShedViewSet,
    StorageTypeViewSet,
    StorageLocationViewSet,
    StorageShedViewSet,
    StockViewSet,
    StockTransactionViewSet,
    SuppliersViewSet,
    TotalInventoryViewSet,
    UnitsViewSet,
)


router = DefaultRouter()

router.register(r'categories', CategoriesViewSet)
router.register(r'donors', DonorsViewSet)
router.register(r'donation', DonationViewSet)
router.register(r'goods-receipt', GoodsReceiptViewSet)
router.register(r'item-status', ItemStatusViewSet)
router.register(r'items', ItemsViewSet)
router.register(r'locations', LocationsViewSet)
router.register(r'purchase-order', PurchaseOrderViewSet)
router.register(r'shed', ShedViewSet)
router.register(r'suppliers', SuppliersViewSet)
router.register(r'units', UnitsViewSet)
router.register(r'storage-type', StorageTypeViewSet)
router.register(r'storage-location', StorageLocationViewSet)
router.register(r'storage-shed', StorageShedViewSet)
router.register(r'stock', StockViewSet)
router.register(r'transection', StockTransactionViewSet)
router.register(r'total-inventory', TotalInventoryViewSet, basename='total-inventory')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
    path('', include(router.urls)),
]

