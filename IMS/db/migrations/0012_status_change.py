# Status Change transactions: stock at one storage location moves from one status to another
# (e.g. Serviceable -> Non Serviceable when damaged, back when repaired). The row's status is the new one and
# from_status_id the old one; stock_balance takes the sent side at from_status.

from django.db import migrations

VIEW = '''
CREATE OR REPLACE VIEW stock_balance AS
SELECT row_number() OVER (ORDER BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id) AS row_id,
       storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id, sum(quantity) AS quantity
FROM (
    SELECT to_storage_location_id AS storage_location_id, to_sto_shed_id AS sto_shed_id,
           item_id, sub_cat_id, spec_id, status_id, quantity
    FROM inventory_transaction WHERE to_storage_location_id IS NOT NULL
    UNION ALL
    SELECT from_storage_location_id, from_sto_shed_id, item_id, sub_cat_id, spec_id,
           {from_status}, -quantity
    FROM inventory_transaction WHERE from_storage_location_id IS NOT NULL
) movement
GROUP BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id
HAVING sum(quantity) <> 0;
'''

SQL = '''
ALTER TABLE transaction_type DROP CONSTRAINT transaction_type_direction_check;
ALTER TABLE transaction_type ADD CONSTRAINT transaction_type_direction_check
    CHECK (direction IN ('in', 'out', 'transfer', 'status'));
INSERT INTO transaction_type (type_id, type_name, direction) VALUES (7, 'Status Change', 'status');
SELECT setval(pg_get_serial_sequence('transaction_type', 'type_id'), (SELECT max(type_id) FROM transaction_type));

ALTER TABLE inventory_transaction ADD COLUMN from_status_id bigint REFERENCES item_status (status_id);
-- A status change stays at one storage location.
ALTER TABLE inventory_transaction ADD CONSTRAINT inventory_transaction_status_change_check
    CHECK (from_status_id IS NULL OR from_storage_location_id = to_storage_location_id);
''' + VIEW.format(from_status='coalesce(from_status_id, status_id)')

REVERSE_SQL = VIEW.format(from_status='status_id') + '''
DELETE FROM inventory_transaction WHERE txn_type_id = 7;
ALTER TABLE inventory_transaction DROP CONSTRAINT inventory_transaction_status_change_check;
ALTER TABLE inventory_transaction DROP COLUMN from_status_id;
DELETE FROM transaction_type WHERE type_id = 7;
ALTER TABLE transaction_type DROP CONSTRAINT transaction_type_direction_check;
ALTER TABLE transaction_type ADD CONSTRAINT transaction_type_direction_check
    CHECK (direction IN ('in', 'out', 'transfer'));
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0011_demands'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
