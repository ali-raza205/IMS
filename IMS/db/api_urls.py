from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    CategoriesViewSet,
    DispatchPurposeViewSet,
    InventoryTransactionViewSet,
    ItemConditionViewSet,
    ItemSpecViewSet,
    ItemStatusViewSet,
    ItemSubCategoryViewSet,
    ItemsViewSet,
    LocationsViewSet,
    LoginView,
    MeView,
    PartyViewSet,
    ShedViewSet,
    StockOwnerViewSet,
    StockViewSet,
    StorageLocationViewSet,
    StorageShedViewSet,
    StorageTypeViewSet,
    TotalInventoryViewSet,
    TransactionTypeViewSet,
    UnitsViewSet,
)
from .dashboard import DashboardView
from .demand_dashboard import DemandDashboardView
from .demands import DemandLineViewSet, DemandViewSet


router = DefaultRouter()

router.register(r'categories', CategoriesViewSet)
router.register(r'item-status', ItemStatusViewSet)
router.register(r'item-condition', ItemConditionViewSet)
router.register(r'stock-owner', StockOwnerViewSet)
router.register(r'dispatch-purpose', DispatchPurposeViewSet)
router.register(r'items', ItemsViewSet)
router.register(r'item-sub-category', ItemSubCategoryViewSet)
router.register(r'item-spec', ItemSpecViewSet)
router.register(r'transaction-type', TransactionTypeViewSet)
router.register(r'parties', PartyViewSet)
router.register(r'transactions', InventoryTransactionViewSet)
router.register(r'demands', DemandViewSet)
router.register(r'demand-lines', DemandLineViewSet)
router.register(r'locations', LocationsViewSet)
router.register(r'shed', ShedViewSet)
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
    path('dashboard/demands/', DemandDashboardView.as_view(), name='dashboard-demands'),
    path('', include(router.urls)),
]

