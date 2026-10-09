import datetime
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError as APIValidationError

from .dashboard import dashboard_filters, filtered_records
from .models import InventoryTransaction, Locations, StockBalance, StorageLocation, TransactionType, UserProfile
from .permissions import IsMasterOrCreateOnly, IsMasterOrReadOnly, limit_to_location
from .serializers import InventoryTransactionSerializer, sides_used, stock_keys, user_info


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


class InventoryTransactionTests(SimpleTestCase):
    def test_direction_decides_which_storage_location_sides_are_filled(self):
        self.assertEqual(sides_used(TransactionType.IN), ('to',))
        self.assertEqual(sides_used(TransactionType.OUT), ('from',))
        self.assertEqual(sides_used(TransactionType.TRANSFER), ('from', 'to'))

    def test_stock_keys_cover_both_sides_of_a_transfer(self):
        txn = InventoryTransaction(
            item_id=1, sub_cat_id=2, spec_id=3, status_id=1, quantity=5,
            from_storage_location_id=3, from_sto_shed_id=9, to_storage_location_id=1,
        )
        self.assertEqual(stock_keys(txn), {(3, 9, 1, 2, 3, 1), (1, None, 1, 2, 3, 1)})

    def test_receiving_side_is_not_limited_to_the_users_storage_location(self):
        request = SimpleNamespace(user=location_user())
        fields = InventoryTransactionSerializer(context={'request': request}).fields
        self.assertIn('"storage_location"."st_loc_id" = 3', str(fields['from_storage_location'].queryset.query))
        self.assertNotIn('WHERE', str(fields['to_storage_location'].queryset.all().query))
        self.assertFalse(fields['status'].required)


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
