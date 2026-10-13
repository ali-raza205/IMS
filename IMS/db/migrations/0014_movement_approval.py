# Warehouse movements need approval; districts manage their own stock.
#
# - Transaction types: Dispatch to District (warehouse -> district) and Return (district -> warehouse), next to
#   Internal Transfer (warehouse -> warehouse, shed -> shed) and Dispatch (a district's own use, out of stock).
# - Status Repairable, so returns can be split into fine, repairable and non serviceable stock.
# - dispatch_purpose: why a district used its stock (relief distribution, rescue operation...).
# - approval_status on transactions: pending movements count for nothing until approved (DG PDMA for warehouse
#   movements and returns, the inspection team for status changes); stock_balance only counts approved ones.
# - Inspection team role.

from django.db import migrations, models

APPROVED_VIEW = '''
DROP VIEW stock_balance;
CREATE VIEW stock_balance AS
SELECT row_number() OVER (ORDER BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id, owner_id)
           AS row_id,
       storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id, owner_id, sum(quantity) AS quantity
FROM (
    SELECT to_storage_location_id AS storage_location_id, to_sto_shed_id AS sto_shed_id,
           item_id, sub_cat_id, spec_id, status_id, owner_id, quantity
    FROM inventory_transaction WHERE to_storage_location_id IS NOT NULL{approved}
    UNION ALL
    SELECT from_storage_location_id, from_sto_shed_id, item_id, sub_cat_id, spec_id,
           coalesce(from_status_id, status_id), coalesce(from_owner_id, owner_id), -quantity
    FROM inventory_transaction WHERE from_storage_location_id IS NOT NULL{approved}
) movement
GROUP BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id, owner_id
HAVING sum(quantity) <> 0;
'''

SQL = '''
INSERT INTO transaction_type (type_id, type_name, direction) VALUES
    (8, 'Dispatch to District', 'transfer'),
    (9, 'Return', 'transfer');
SELECT setval(pg_get_serial_sequence('transaction_type', 'type_id'), (SELECT max(type_id) FROM transaction_type));

INSERT INTO item_status (status_id, status_name)
SELECT 3, 'Repairable' WHERE NOT EXISTS (SELECT 1 FROM item_status WHERE status_id = 3);
SELECT setval(pg_get_serial_sequence('item_status', 'status_id'), (SELECT max(status_id) FROM item_status));

CREATE TABLE dispatch_purpose (
    purpose_id bigserial PRIMARY KEY,
    purpose_name varchar(100) NOT NULL UNIQUE,
    is_active boolean NOT NULL DEFAULT true
);
INSERT INTO dispatch_purpose (purpose_name) VALUES
    ('Relief Distribution'), ('Rescue Operation'), ('Consumed in Operations'), ('Loaned'), ('Other');

ALTER TABLE inventory_transaction
    ADD COLUMN purpose_id bigint REFERENCES dispatch_purpose (purpose_id),
    ADD COLUMN approval_status varchar(10) NOT NULL DEFAULT 'approved'
        CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    ADD COLUMN approved_by bigint,
    ADD COLUMN approved_at timestamp,
    ADD COLUMN approval_remarks text;
CREATE INDEX inventory_transaction_approval_idx ON inventory_transaction (approval_status)
    WHERE approval_status <> 'approved';
''' + APPROVED_VIEW.format(approved=" AND approval_status = 'approved'")

REVERSE_SQL = APPROVED_VIEW.format(approved='') + '''
DELETE FROM inventory_transaction WHERE approval_status <> 'approved' OR txn_type_id IN (8, 9);
ALTER TABLE inventory_transaction
    DROP COLUMN purpose_id, DROP COLUMN approval_status, DROP COLUMN approved_by, DROP COLUMN approved_at,
    DROP COLUMN approval_remarks;
DROP TABLE dispatch_purpose;
DELETE FROM transaction_type WHERE type_id IN (8, 9);
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0013_ndma_role_and_stock_owner'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(choices=[('ndma', 'NDMA'), ('master', 'Master'), ('all_areas', 'All areas user'), ('location', 'Storage location user'), ('inspection', 'Inspection team')], default='location', max_length=20),
        ),
        migrations.CreateModel(
            name='DispatchPurpose',
            fields=[
                ('purpose_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('purpose_name', models.CharField(max_length=100, unique=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'dispatch_purpose',
                'managed': False,
            },
        ),
    ]
