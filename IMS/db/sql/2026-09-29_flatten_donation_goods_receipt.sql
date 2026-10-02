-- Flatten donation and goods_receipt to match purchase_order:
-- line items move from the *_detail tables into a JSON `details` column,
-- and the first line's item/quantity/etc. are stored on the record itself.
--
-- Written when donation, donation_detail, goods_receipt and goods_receipt_detail
-- were all empty. The NOT NULL columns below fail (and the whole script rolls back)
-- if donation or goods_receipt have rows by the time this runs.

BEGIN;

DROP TABLE donation_detail;
DROP TABLE goods_receipt_detail;

ALTER TABLE donation
    ADD COLUMN item_id bigint NOT NULL REFERENCES items ("Item_id"),
    ADD COLUMN quantity numeric(15, 2) NOT NULL,
    ADD COLUMN estimated_unit_value numeric(15, 2),
    ADD COLUMN batch_no varchar(100),
    ADD COLUMN details text,
    ADD COLUMN manufacturing_date date,
    ADD COLUMN expiry_date date,
    ADD COLUMN sto_shed_id bigint REFERENCES storage_shed (sto_shed_id);

ALTER TABLE goods_receipt
    ADD COLUMN item_id bigint NOT NULL REFERENCES items ("Item_id"),
    ADD COLUMN received_quantity numeric(15, 2) NOT NULL,
    ADD COLUMN unit_cost numeric(15, 2),
    ADD COLUMN batch_no varchar(100),
    ADD COLUMN details text,
    ADD COLUMN manufacturing_date date,
    ADD COLUMN expiry_date date,
    ADD COLUMN sto_shed_id bigint REFERENCES storage_shed (sto_shed_id);

COMMIT;
