# TODO: Add Purchase-to-Stock Auto-Update

## Goal
When a GoodsReceipt is created against a PurchaseOrder, automatically:
1. Create GoodsReceiptDetail records from the `details` JSON
2. Auto-update or create Stock entries for each received item

## Steps

### Phase 1: Restructure GoodsReceipt Serializer
- [ ] **Step 1:** Modify `GoodsReceiptSerializer` in `serializers.py`
  - Add `po_id` as writable PrimaryKeyRelatedField
  - Add `details` as JSONField (array of items with item_id, received_quantity, batch_no, etc.)
  - Override `create()` to save GR + create GoodsReceiptDetail records
  - Override `to_representation()` to show nested PO & details

### Phase 2: Add Stock Update Logic in Views
- [ ] **Step 2:** Modify `GoodsReceiptViewSet` in `api_views.py`
  - Add helper: `_get_storage_shed_from_po(po)` → resolves Locations → StorageLocation → StorageShed
  - Add helper: `_get_unit_from_item(item)` → gets unit name from Items.unit_id → Units
  - Add helper: `_update_stock(gr, item, quantity, unit, batch_no, mfg_date, exp_date, unit_cost, location_shed)`
    - Upsert logic: check Stock by item+location, create or update quantity
  - Override `perform_create()` to call stock update after GR creation

### Phase 3: Verify
- [ ] **Step 3:** Run Django server and test the API endpoint
