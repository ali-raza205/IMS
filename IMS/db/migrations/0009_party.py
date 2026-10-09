# Suppliers, donors and NDMA go into one `party` table, each under its transaction type
# (suppliers under Procurement, donors under Donation, NDMA under NDMA), like items under categories.
# Transactions get one `party_id` instead of `supplier_id` and `donor_id`; donors and suppliers are dropped.

from django.db import migrations, models

PROCUREMENT, DONATION, NDMA = 2, 1, 3

SQL = f'''
CREATE TABLE party (
    party_id bigserial PRIMARY KEY,
    party_name text NOT NULL,
    txn_type_id bigint NOT NULL REFERENCES transaction_type (type_id),
    contact_person text,
    phone text,
    email text,
    address text,
    ntn text,
    gst text,
    is_active boolean NOT NULL DEFAULT true
);
-- Names are unique per transaction type, ignoring case and surrounding spaces.
CREATE UNIQUE INDEX party_name_unique ON party (txn_type_id, lower(btrim(party_name)));

ALTER TABLE inventory_transaction ADD COLUMN party_id bigint REFERENCES party (party_id);
CREATE INDEX inventory_transaction_party_idx ON inventory_transaction (party_id);

-- Existing suppliers and donors, with the transactions that used them
INSERT INTO party (party_name, txn_type_id, contact_person, phone, email, address, ntn, gst, is_active)
SELECT btrim(supplier_name), {PROCUREMENT}, contact_person, phone, email, address, ntn, gst, coalesce(active, true)
FROM suppliers;
UPDATE inventory_transaction t SET party_id = p.party_id
FROM suppliers s JOIN party p ON p.txn_type_id = {PROCUREMENT} AND p.party_name = btrim(s.supplier_name)
WHERE t.supplier_id = s.supplier_id;

INSERT INTO party (party_name, txn_type_id, contact_person, phone, email, address, is_active)
SELECT btrim(donor_name), {DONATION}, contact_person, phone, email, address, coalesce(active, true)
FROM donors;
UPDATE inventory_transaction t SET party_id = p.party_id
FROM donors d JOIN party p ON p.txn_type_id = {DONATION} AND p.party_name = btrim(d.donor_name)
WHERE t.donor_id = d.donor_id;

-- NDMA is the party of every NDMA receipt
INSERT INTO party (party_name, txn_type_id) VALUES ('NDMA', {NDMA});
UPDATE inventory_transaction SET party_id = (SELECT party_id FROM party WHERE txn_type_id = {NDMA})
WHERE txn_type_id = {NDMA};

-- A party must be of the transaction's own type.
ALTER TABLE party ADD CONSTRAINT party_id_type_unique UNIQUE (party_id, txn_type_id);
ALTER TABLE inventory_transaction ADD CONSTRAINT inventory_transaction_party_type_fkey
    FOREIGN KEY (party_id, txn_type_id) REFERENCES party (party_id, txn_type_id);

ALTER TABLE inventory_transaction DROP COLUMN supplier_id, DROP COLUMN donor_id;
DROP TABLE suppliers;
DROP TABLE donors;
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0008_item_lookups_and_inventory_transaction'),
    ]

    operations = [
        migrations.RunSQL(SQL),
        migrations.CreateModel(
            name='Party',
            fields=[
                ('party_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('party_name', models.TextField()),
                ('contact_person', models.TextField(blank=True, null=True)),
                ('phone', models.TextField(blank=True, null=True)),
                ('email', models.TextField(blank=True, null=True)),
                ('address', models.TextField(blank=True, null=True)),
                ('ntn', models.TextField(blank=True, null=True)),
                ('gst', models.TextField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'party',
                'managed': False,
            },
        ),
        migrations.DeleteModel(
            name='Donors',
        ),
        migrations.DeleteModel(
            name='Suppliers',
        ),
    ]
