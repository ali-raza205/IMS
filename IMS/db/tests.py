import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .serializers import DonationSerializer, GoodsReceiptSerializer, PurchaseOrderSerializer


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
