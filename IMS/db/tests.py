import datetime
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError as APIValidationError

from .dashboard import dashboard_filters, filtered_records
from .models import (
    DemandLine,
    InventoryTransaction,
    Locations,
    StockBalance,
    StorageLocation,
    StorageType,
    TransactionType,
    UserProfile,
)
from .permissions import IsMasterOrCreateOnly, IsMasterOrReadOnly, can_decide_demand_line, limit_to_location
from .serializers import (
    InventoryTransactionSerializer,
    add_months,
    movement_errors,
    needed_approval,
    sides_used,
    stock_keys,
    user_info,
    user_role,
)


def location_user(st_loc_id=3):
    user = User(id=5, username='mzg')
    area = Locations(location_id=24, location_name='Muzaffargarh')
    storage_location = StorageLocation(st_loc_id=st_loc_id, details='Muzaffargarh Warehouse', location=area)
    UserProfile(user=user, role=UserProfile.ROLE_LOCATION, storage_location=storage_location)
    return user


class StorageLocationScopeTests(SimpleTestCase):
    def test_user_info_reports_storage_location_and_its_area(self):
        info = user_info(location_user())
        self.assertEqual(info['role'], 'location')
        self.assertEqual(info['storage_location_id'], 3)
        self.assertEqual(info['storage_location_name'], 'Muzaffargarh Warehouse')
        self.assertEqual(info['location_id'], 24)
        self.assertEqual(info['location_name'], 'Muzaffargarh')

    def test_location_user_is_limited_to_their_storage_location(self):
        user = location_user()
        txn_sql = str(limit_to_location(InventoryTransaction.objects.all(), user).query)
        self.assertIn('"inventory_transaction"."from_storage_location_id" = 3', txn_sql)
        self.assertIn('OR "inventory_transaction"."to_storage_location_id" = 3', txn_sql)
        stock_sql = str(limit_to_location(StockBalance.objects.all(), user).query)
        self.assertIn('"stock_balance"."storage_location_id" = 3', stock_sql)

    def test_all_areas_user_sees_every_storage_location_but_is_not_master(self):
        user = User(id=6, username='province')
        UserProfile(user=user, role=UserProfile.ROLE_ALL_AREAS)
        self.assertNotIn('WHERE', str(limit_to_location(InventoryTransaction.objects.all(), user).query))
        self.assertEqual(user_info(user)['role'], 'all_areas')

        def allowed(permission, method):
            return permission().has_permission(SimpleNamespace(method=method, user=user), None)

        # Lookup data: read and add like everyone else, but no edit/delete; areas and storage locations read-only.
        self.assertTrue(allowed(IsMasterOrCreateOnly, 'POST'))
        self.assertFalse(allowed(IsMasterOrCreateOnly, 'PUT'))
        self.assertFalse(allowed(IsMasterOrCreateOnly, 'DELETE'))
        self.assertFalse(allowed(IsMasterOrReadOnly, 'POST'))

    def test_storage_location_user_needs_a_storage_location(self):
        with self.assertRaises(ValidationError):
            UserProfile(role=UserProfile.ROLE_LOCATION).clean()
        UserProfile(role=UserProfile.ROLE_MASTER).clean()
        UserProfile(role=UserProfile.ROLE_LOCATION, storage_location_id=3).clean()


class DemandApprovalRoleTests(SimpleTestCase):
    def user(self, role, st_loc_id=None):
        user = User(id=7, username=role)
        UserProfile(user=user, role=role, storage_location_id=st_loc_id)
        return user

    def line(self, referred_to_id=None, district=False, owner_id=1):
        location = None
        if referred_to_id is not None:
            location = StorageLocation(st_loc_id=referred_to_id,
                                       type_id=StorageType.DISTRICT if district else StorageType.WAREHOUSE)
        return DemandLine(referred_to=location, referred_owner_id=owner_id)

    def test_pdma_admin_decides_lines_from_warehouses(self):
        master = self.user(UserProfile.ROLE_MASTER)
        superuser = SimpleNamespace(username='pdma_admin', is_superuser=True, profile=None)  # no role, like pdma_admin
        for user in (master, superuser):
            with self.subTest(user=user.username):
                self.assertTrue(can_decide_demand_line(user, self.line(1)))
                self.assertTrue(can_decide_demand_line(user, self.line()))
                self.assertFalse(can_decide_demand_line(user, self.line(1, owner_id=2)))
                self.assertFalse(can_decide_demand_line(user, self.line(9, district=True)))
        self.assertEqual(user_role(superuser), UserProfile.ROLE_MASTER)

    def test_only_ndma_decides_lines_referred_to_ndma(self):
        ndma = self.user(UserProfile.ROLE_NDMA)
        self.assertTrue(can_decide_demand_line(ndma, self.line(owner_id=2)))
        self.assertFalse(can_decide_demand_line(ndma, self.line(1)))
        self.assertFalse(can_decide_demand_line(self.user(UserProfile.ROLE_LOCATION, 1), self.line(1, owner_id=2)))

    def test_district_decides_returns_asked_from_it(self):
        self.assertTrue(can_decide_demand_line(self.user(UserProfile.ROLE_LOCATION, 9), self.line(9, district=True)))
        self.assertFalse(can_decide_demand_line(self.user(UserProfile.ROLE_LOCATION, 8), self.line(9, district=True)))

    def test_warehouses_only_issue(self):
        for role in (UserProfile.ROLE_LOCATION, UserProfile.ROLE_ALL_AREAS, UserProfile.ROLE_INSPECTION):
            with self.subTest(role=role):
                user = self.user(role, 1)
                self.assertFalse(can_decide_demand_line(user, self.line(1)))
                self.assertFalse(can_decide_demand_line(user, self.line(1, owner_id=2)))

    def test_ndma_sees_only_its_own_stock_and_has_no_master_powers(self):
        ndma = self.user(UserProfile.ROLE_NDMA)
        self.assertFalse(IsMasterOrReadOnly().has_permission(SimpleNamespace(method='DELETE', user=ndma), None))
        txn_sql = str(limit_to_location(InventoryTransaction.objects.all(), ndma).query)
        self.assertIn('"inventory_transaction"."owner_id" = 2', txn_sql)
        self.assertIn('"inventory_transaction"."from_owner_id" = 2', txn_sql)
        self.assertIn('"stock_balance"."owner_id" = 2', str(limit_to_location(StockBalance.objects.all(), ndma).query))
        self.assertNotIn('WHERE', str(limit_to_location(StorageLocation.objects.all(), ndma).query))

    def test_me_reports_who_can_approve_demands(self):
        self.assertFalse(user_info(location_user())['can_approve_demands'])
        self.assertTrue(user_info(self.user(UserProfile.ROLE_NDMA))['can_approve_demands'])

    def test_ndma_needs_no_storage_location(self):
        UserProfile(role=UserProfile.ROLE_NDMA).clean()
        with self.assertRaises(ValidationError):
            UserProfile(role=UserProfile.ROLE_LOCATION).clean()


class MovementRuleTests(SimpleTestCase):
    warehouse = StorageLocation(st_loc_id=1, type_id=StorageType.WAREHOUSE)
    warehouse2 = StorageLocation(st_loc_id=3, type_id=StorageType.WAREHOUSE)
    district = StorageLocation(st_loc_id=2, type_id=StorageType.DISTRICT)
    district2 = StorageLocation(st_loc_id=6, type_id=StorageType.DISTRICT)
    department = SimpleNamespace(pk=50)

    def errors(self, type_id, frm, to, party=None, ndma=False, owner=1, from_shed=None, to_shed=None):
        return movement_errors(TransactionType(type_id=type_id), frm, to, from_shed, to_shed, party, ndma, owner)

    def test_dispatch_goes_to_a_district_or_a_department(self):
        self.assertEqual(self.errors(4, self.warehouse, self.district), {})
        self.assertEqual(self.errors(4, self.district, self.district2), {})
        self.assertEqual(self.errors(4, self.district, None, party=self.department), {})
        self.assertIn('to_storage_location', self.errors(4, self.warehouse, self.warehouse2))  # that is shifting
        self.assertIn('to_storage_location', self.errors(4, self.district, None))
        self.assertIn('party', self.errors(4, self.district, self.district2, party=self.department))

    def test_ndma_stock_is_dispatched_only_to_warehouses(self):
        self.assertEqual(self.errors(4, self.warehouse, None, ndma=True, owner=2), {})
        self.assertEqual(self.errors(4, self.warehouse, self.warehouse2, ndma=True, owner=2), {})
        self.assertIn('to_storage_location', self.errors(4, self.warehouse, self.district, ndma=True, owner=2))

    def test_internal_transfer_is_warehouse_to_warehouse(self):
        self.assertEqual(self.errors(5, self.warehouse, self.warehouse2), {})
        self.assertEqual(self.errors(5, self.warehouse, self.warehouse, from_shed=1, to_shed=2), {})
        self.assertIn('txn_type', self.errors(5, self.warehouse, self.district))
        self.assertIn('txn_type', self.errors(5, self.district, self.warehouse))
        self.assertIn('to_storage_location', self.errors(5, self.warehouse, self.warehouse))

    def test_returns(self):
        self.assertEqual(self.errors(9, self.district, self.warehouse), {})
        self.assertIn('to_storage_location', self.errors(9, self.district, self.district2))
        self.assertEqual(self.errors(9, self.warehouse, None, owner=2), {})  # NDMA stock back to NDMA
        self.assertIn('to_storage_location', self.errors(9, self.warehouse, None, owner=1))

    def test_shelf_life_sets_the_expiry_date(self):
        self.assertEqual(add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))
        self.assertEqual(add_months(datetime.date(2026, 10, 15), 24), datetime.date(2028, 10, 15))
        self.assertEqual(add_months(datetime.date(2026, 12, 1), 1), datetime.date(2027, 1, 1))

    def test_what_waits_for_approval(self):
        user = location_user()
        dispatch = TransactionType(type_id=4, direction=TransactionType.OUT)
        self.assertEqual(needed_approval(dispatch, self.district, None, user), InventoryTransaction.APPROVED)
        self.assertEqual(needed_approval(dispatch, self.district, self.district2, user), InventoryTransaction.PENDING)
        self.assertEqual(needed_approval(dispatch, self.warehouse, self.district, user), InventoryTransaction.PENDING)
        dg = SimpleNamespace(username='dg', is_superuser=True, profile=None)
        self.assertEqual(needed_approval(dispatch, self.warehouse, self.district, dg), InventoryTransaction.APPROVED)
        self.assertEqual(needed_approval(dispatch, self.warehouse, None, dg, ndma_handover=True), InventoryTransaction.PENDING)


class InventoryTransactionTests(SimpleTestCase):
    def test_direction_decides_which_storage_location_sides_are_filled(self):
        self.assertEqual(sides_used(TransactionType.IN), ('to',))
        self.assertEqual(sides_used(TransactionType.OUT), ('from',))
        self.assertEqual(sides_used(TransactionType.TRANSFER), ('from', 'to'))

    def test_stock_keys_cover_both_sides_of_a_transfer(self):
        txn = InventoryTransaction(
            item_id=1, sub_cat_id=2, spec_id=3, status_id=1, condition_id=1, quantity=5,
            from_storage_location_id=3, from_sto_shed_id=9, to_storage_location_id=1,
        )
        self.assertEqual(stock_keys(txn), {(3, 9, 1, 2, 3, 1, 1, 1), (1, None, 1, 2, 3, 1, 1, 1)})

    def test_handing_ndma_stock_to_pdma_takes_it_from_ndma(self):
        txn = InventoryTransaction(item_id=1, sub_cat_id=None, spec_id=None, status_id=1, condition_id=1, quantity=5, owner_id=1,
                                   from_owner_id=2, from_storage_location_id=6, to_storage_location_id=3)
        self.assertEqual(stock_keys(txn), {(6, None, 1, None, None, 1, 2, 1), (3, None, 1, None, None, 1, 1, 1)})

    def test_status_change_takes_stock_from_the_old_status_and_condition(self):
        txn = InventoryTransaction(
            item_id=1, sub_cat_id=None, spec_id=None, from_status_id=1, from_condition_id=1, status_id=2,
            condition_id=3, quantity=3,
            from_storage_location_id=1, from_sto_shed_id=4, to_storage_location_id=1, to_sto_shed_id=4,
        )
        self.assertEqual(stock_keys(txn), {(1, 4, 1, None, None, 1, 1, 1), (1, 4, 1, None, None, 2, 1, 3)})
        self.assertEqual(sides_used(TransactionType.STATUS), ('from', 'to'))

    def test_receiving_side_is_not_limited_to_the_users_storage_location(self):
        request = SimpleNamespace(user=location_user())
        fields = InventoryTransactionSerializer(context={'request': request}).fields
        self.assertIn('"storage_location"."st_loc_id" = 3', str(fields['from_storage_location'].queryset.query))
        self.assertNotIn('WHERE', str(fields['to_storage_location'].queryset.all().query))
        self.assertTrue(fields['status'].required)


class DashboardFilterTests(SimpleTestCase):
    today = datetime.date(2026, 10, 6)

    def sql(self, user, **params):
        return str(filtered_records(user, dashboard_filters(params), self.today).query)

    def test_reads_transactions_of_the_users_storage_location(self):
        sql = self.sql(location_user(), storage_location='9')
        self.assertIn('"inventory_transaction"."from_storage_location_id" = 3', sql)
        self.assertIn('"inventory_transaction"."to_storage_location_id" = 3', sql)
        self.assertIn('COALESCE("inventory_transaction"."to_storage_location_id", '
                      '"inventory_transaction"."from_storage_location_id") IN (9)', sql)

    def test_type_item_and_category_filters(self):
        sql = self.sql(location_user(), txn_type='1,2', direction='in', category='2,5', item='7', sub_category='4',
                       spec='8', status='2')
        self.assertIn('"inventory_transaction"."txn_type_id" IN (1, 2)', sql)
        self.assertIn('"transaction_type"."direction" IN (in)', sql)
        self.assertIn('"items"."item_category" IN (2, 5)', sql)
        self.assertIn('"inventory_transaction"."item_id" IN (7)', sql)
        self.assertIn('"inventory_transaction"."sub_cat_id" IN (4)', sql)
        self.assertIn('"inventory_transaction"."spec_id" IN (8)', sql)
        self.assertIn('"inventory_transaction"."status_id" IN (2)', sql)

    def test_expiry_filters_use_the_records_expiry_date(self):
        sql = self.sql(location_user(), expiry_status='expired,expiring', expiring_days='60', expiry_to='2027-01-31')
        self.assertIn('"inventory_transaction"."expiry_date" <= 2026-12-05', sql)  # today + 60 days
        self.assertIn('"inventory_transaction"."expiry_date" <= 2027-01-31', sql)

    def test_invalid_filters_are_rejected(self):
        for params in ({'category': 'food'}, {'expiry_status': 'soon'}, {'direction': 'sideways'},
                       {'txn_type': 'donation'}, {'expiring_days': '-1'}, {'expiry_from': '06/10/2026'}):
            with self.subTest(params=params), self.assertRaises(APIValidationError):
                dashboard_filters(params)
