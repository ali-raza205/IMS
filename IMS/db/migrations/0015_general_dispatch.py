# Dispatch is one general type again: to a district (a storage location) or to a department (a party of the
# Dispatch type). Dispatch to District (type 8) is folded into it, and a first list of departments is added.

from django.db import migrations

DISPATCH, DISPATCH_TO_DISTRICT = 4, 8
DEPARTMENTS = (
    'District Administration (DC Office)', 'Rescue 1122', 'Health Department', 'Civil Defence',
    'Local Government', 'Pakistan Army', 'Irrigation Department', 'Other Department',
)

SQL = f'''
UPDATE inventory_transaction SET txn_type_id = {DISPATCH} WHERE txn_type_id = {DISPATCH_TO_DISTRICT};
DELETE FROM transaction_type WHERE type_id = {DISPATCH_TO_DISTRICT};
INSERT INTO party (party_name, txn_type_id)
SELECT name, {DISPATCH} FROM (VALUES {', '.join(f"('{name}')" for name in DEPARTMENTS)}) AS departments(name)
WHERE NOT EXISTS (SELECT 1 FROM party p WHERE p.txn_type_id = {DISPATCH} AND lower(p.party_name) = lower(name));
'''

REVERSE_SQL = f'''
INSERT INTO transaction_type (type_id, type_name, direction) VALUES ({DISPATCH_TO_DISTRICT}, 'Dispatch to District', 'transfer');
DELETE FROM party WHERE txn_type_id = {DISPATCH}
    AND party_id NOT IN (SELECT party_id FROM inventory_transaction WHERE party_id IS NOT NULL);
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0014_movement_approval'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
