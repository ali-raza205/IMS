from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    CategoriesViewSet,
    DonorsViewSet,
    InventoryTransactionViewSet,
    ItemSpecViewSet,
    ItemStatusViewSet,
    ItemSubCategoryViewSet,
    ItemsViewSet,
    LocationsViewSet,
    LoginView,
    MeView,
    ShedViewSet,
    StockViewSet,
    StorageLocationViewSet,
    StorageShedViewSet,
    StorageTypeViewSet,
    SuppliersViewSet,
    TotalInventoryViewSet,
    TransactionTypeViewSet,
    UnitsViewSet,
)
from .dashboard import DashboardView


router = DefaultRouter()

router.register(r'categories', CategoriesViewSet)
router.register(r'donors', DonorsViewSet)
router.register(r'item-status', ItemStatusViewSet)
router.register(r'items', ItemsViewSet)
router.register(r'item-sub-category', ItemSubCategoryViewSet)
router.register(r'item-spec', ItemSpecViewSet)
router.register(r'transaction-type', TransactionTypeViewSet)
router.register(r'transactions', InventoryTransactionViewSet)
router.register(r'locations', LocationsViewSet)
router.register(r'shed', ShedViewSet)
router.register(r'suppliers', SuppliersViewSet)
router.register(r'units', UnitsViewSet)
router.register(r'storage-type', StorageTypeViewSet)
router.register(r'storage-location', StorageLocationViewSet)
router.register(r'storage-shed', StorageShedViewSet)
router.register(r'stock', StockViewSet)
router.register(r'total-inventory', TotalInventoryViewSet, basename='total-inventory')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]

