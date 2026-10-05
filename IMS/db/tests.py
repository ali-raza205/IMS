import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import Locations, PurchaseOrder, Stock, StorageLocation, UserProfile
from .permissions import IsMasterOrCreateOnly, IsMasterOrReadOnly, limit_to_location
from .serializers import DonationSerializer, GoodsReceiptSerializer, PurchaseOrderSerializer, user_info


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
        po_sql = str(limit_to_location(PurchaseOrder.objects.all(), user).query)
        self.assertIn('"purchase_order"."location_id" = 3', po_sql)
        stock_sql = str(limit_to_location(Stock.objects.all(), user).query)
        self.assertIn('"storage_shed"."sto_loc_id" = 3', stock_sql)

    def test_all_areas_user_sees_every_storage_location_but_is_not_master(self):
        user = User(id=6, username='province')
        UserProfile(user=user, role=UserProfile.ROLE_ALL_AREAS)
        self.assertNotIn('WHERE', str(limit_to_location(PurchaseOrder.objects.all(), user).query))
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


class PurchaseOrderSerializerTests(SimpleTestCase):
    def test_create_stores_detail_payload_on_purchase_order_record(self):
        serializer = PurchaseOrderSerializer()
        details_payload = [
            {
                'item_id': 7,
                'quantity': '10.50',
                'unit_price': '25.00',
                'remarks': 'bulk order',
            }
        ]

        with patch('db.serializers.PurchaseOrder.objects.create', return_value=object()) as create_mock:
            serializer.create({
                'po_number': 'PO-1001',
                'details': details_payload,
            })

        create_kwargs = create_mock.call_args.kwargs
        self.assertEqual(create_kwargs['po_number'], 'PO-1001')
        self.assertEqual(create_kwargs['item_id'], 7)
        self.assertEqual(create_kwargs['quantity'], '10.50')
        self.assertEqual(create_kwargs['unit_price'], '25.00')
        self.assertEqual(json.loads(create_kwargs['details']), details_payload)

    def test_received_date_is_optional_date_field(self):
        field = PurchaseOrderSerializer().fields['received_date']
        self.assertFalse(field.required)
        self.assertTrue(field.allow_null)
        self.assertEqual(str(field.to_internal_value('2026-10-05')), '2026-10-05')


class DonationSerializerTests(SimpleTestCase):
    def test_create_stores_detail_payload_on_donation_record(self):
        serializer = DonationSerializer()
        details_payload = [
            {
                'item_id': 3,
                'quantity': '40.00',
                'estimated_unit_value': '12.00',
                'batch_no': 'B-9',
                'expiry_date': '2027-01-31',
            },
            {'item_id': 4, 'quantity': '5.00'},
        ]

        with patch('db.serializers.Donation.objects.create', return_value=object()) as create_mock:
            serializer.create({
                'donation_no': 'DN-1',
                'details': details_payload,
            })

        create_kwargs = create_mock.call_args.kwargs
        self.assertEqual(create_kwargs['donation_no'], 'DN-1')
        self.assertEqual(create_kwargs['item_id'], 3)
        self.assertEqual(create_kwargs['quantity'], '40.00')
        self.assertEqual(create_kwargs['estimated_unit_value'], '12.00')
        self.assertEqual(create_kwargs['batch_no'], 'B-9')
        self.assertEqual(create_kwargs['expiry_date'], '2027-01-31')
        self.assertEqual(json.loads(create_kwargs['details']), details_payload)

    def test_received_date_is_optional_date_field(self):
        field = DonationSerializer().fields['received_date']
        self.assertFalse(field.required)
        self.assertTrue(field.allow_null)
        self.assertEqual(str(field.to_internal_value('2026-10-05')), '2026-10-05')


class GoodsReceiptSerializerTests(SimpleTestCase):
    def test_create_stores_detail_payload_on_goods_receipt_record(self):
        serializer = GoodsReceiptSerializer()
        details_payload = [
            {'item_id': 9, 'received_quantity': '8.00', 'unit_cost': '3.50'},
        ]

        with patch('db.serializers.GoodsReceipt.objects.create', return_value=object()) as create_mock:
            serializer.create({
                'grn_no': 'GRN-1',
                'details': details_payload,
            })

        create_kwargs = create_mock.call_args.kwargs
        self.assertEqual(create_kwargs['item_id'], 9)
        self.assertEqual(create_kwargs['received_quantity'], '8.00')
        self.assertEqual(create_kwargs['unit_cost'], '3.50')
        self.assertEqual(json.loads(create_kwargs['details']), details_payload)

    def test_create_ignores_non_object_detail_lines(self):
        serializer = GoodsReceiptSerializer()

        with patch('db.serializers.GoodsReceipt.objects.create', return_value=object()) as create_mock:
            serializer.create({'grn_no': 'GRN-2', 'details': [1, 2]})

        create_kwargs = create_mock.call_args.kwargs
        self.assertNotIn('item_id', create_kwargs)
        self.assertEqual(json.loads(create_kwargs['details']), [1, 2])
