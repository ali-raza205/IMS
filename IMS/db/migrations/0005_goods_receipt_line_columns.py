# The goods_receipt part of sql/2026-09-29_flatten_donation_goods_receipt.sql, which never reached the database.
# Line items live in the JSON `details` column; the first line is copied onto the record.
# goods_receipt is unmanaged, so the columns are added with SQL. The NOT NULL columns need an empty table.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0004_donation_line_columns'),
    ]

    operations = [
        migrations.RunSQL(
            sql='''
                ALTER TABLE goods_receipt
                    ADD COLUMN IF NOT EXISTS item_id bigint NOT NULL REFERENCES items ("Item_id"),
                    ADD COLUMN IF NOT EXISTS received_quantity numeric(15, 2) NOT NULL,
                    ADD COLUMN IF NOT EXISTS unit_cost numeric(15, 2),
                    ADD COLUMN IF NOT EXISTS batch_no varchar(100),
                    ADD COLUMN IF NOT EXISTS details text,
                    ADD COLUMN IF NOT EXISTS manufacturing_date date,
                    ADD COLUMN IF NOT EXISTS expiry_date date,
                    ADD COLUMN IF NOT EXISTS sto_shed_id bigint REFERENCES storage_shed (sto_shed_id);
            ''',
            reverse_sql='''
                ALTER TABLE goods_receipt
                    DROP COLUMN IF EXISTS item_id,
                    DROP COLUMN IF EXISTS received_quantity,
                    DROP COLUMN IF EXISTS unit_cost,
                    DROP COLUMN IF EXISTS batch_no,
                    DROP COLUMN IF EXISTS details,
                    DROP COLUMN IF EXISTS manufacturing_date,
                    DROP COLUMN IF EXISTS expiry_date,
                    DROP COLUMN IF EXISTS sto_shed_id;
            ''',
        ),
    ]
