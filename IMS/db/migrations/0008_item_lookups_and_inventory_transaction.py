# Items get sub categories and specs, and every incoming and outgoing movement goes into one
# inventory_transaction table with a transaction type. Stock on hand becomes the stock_balance view.
#
# The old items are replaced by the catalog in db/data/item_catalog.csv (one row per old item: its new
# item, sub category and spec). Purchase orders and opening stock rows are moved into inventory_transaction
# on the new items, then purchase_order, donation, goods_receipt, stock and stock_transaction are dropped.
# Runs in one database transaction. Take a pg_dump first: there is no way back.

import csv
import re
from pathlib import Path

from django.db import migrations, models

CATALOG = Path(__file__).resolve().parent.parent / 'data' / 'item_catalog.csv'

DONATION, PROCUREMENT, NDMA, DISPATCH, INTERNAL_TRANSFER, OPENING_STOCK = 1, 2, 3, 4, 5, 6
SERVICEABLE, NON_SERVICEABLE = 1, 2

SCHEMA_SQL = '''
UPDATE item_status SET status_name = 'Serviceable' WHERE status_id = 1;
UPDATE item_status SET status_name = 'Non Serviceable' WHERE status_id = 2;

CREATE TABLE transaction_type (
    type_id bigserial PRIMARY KEY,
    type_name varchar(50) NOT NULL UNIQUE,
    direction varchar(10) NOT NULL CHECK (direction IN ('in', 'out', 'transfer'))
);
INSERT INTO transaction_type (type_id, type_name, direction) VALUES
    (1, 'Donation', 'in'),
    (2, 'Procurement', 'in'),
    (3, 'NDMA', 'in'),
    (4, 'Dispatch', 'out'),
    (5, 'Internal Transfer', 'transfer'),
    (6, 'Opening Stock', 'in');
SELECT setval(pg_get_serial_sequence('transaction_type', 'type_id'), 6);

CREATE TABLE item_sub_category (
    sub_cat_id bigserial PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES items ("Item_id"),
    sub_cat_name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true
);
-- Names are unique ignoring case and surrounding spaces: one "Boat", one "Fiberglass" per item, one "19 ft" per sub category.
CREATE UNIQUE INDEX item_sub_category_name_unique ON item_sub_category (item_id, lower(btrim(sub_cat_name)));

CREATE TABLE item_spec (
    spec_id bigserial PRIMARY KEY,
    item_id bigint NOT NULL REFERENCES items ("Item_id"),
    sub_cat_id bigint REFERENCES item_sub_category (sub_cat_id),
    spec_name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX item_spec_name_unique ON item_spec (item_id, sub_cat_id, lower(btrim(spec_name))) NULLS NOT DISTINCT;

CREATE TABLE inventory_transaction (
    txn_id bigserial PRIMARY KEY,
    txn_no varchar(50),
    txn_type_id bigint NOT NULL REFERENCES transaction_type (type_id),
    txn_date date NOT NULL,
    item_id bigint NOT NULL REFERENCES items ("Item_id"),
    sub_cat_id bigint REFERENCES item_sub_category (sub_cat_id),
    spec_id bigint REFERENCES item_spec (spec_id),
    status_id bigint NOT NULL DEFAULT 1 REFERENCES item_status (status_id),
    quantity numeric(15, 2) NOT NULL CHECK (quantity > 0),
    unit_price numeric(15, 2),
    from_storage_location_id bigint REFERENCES storage_location (st_loc_id),
    from_sto_shed_id bigint REFERENCES storage_shed (sto_shed_id),
    to_storage_location_id bigint REFERENCES storage_location (st_loc_id),
    to_sto_shed_id bigint REFERENCES storage_shed (sto_shed_id),
    supplier_id bigint REFERENCES suppliers (supplier_id),
    donor_id bigint REFERENCES donors (donor_id),
    issued_to text,
    invoice_no varchar(100),
    invoice_date date,
    batch_no varchar(100),
    manufacturing_date date,
    expiry_date date,
    remarks text,
    created_by bigint,
    created_at timestamp,
    CHECK (from_storage_location_id IS NOT NULL OR to_storage_location_id IS NOT NULL)
);
CREATE INDEX inventory_transaction_item_idx ON inventory_transaction (item_id, sub_cat_id, spec_id);
CREATE INDEX inventory_transaction_from_idx ON inventory_transaction (from_storage_location_id);
CREATE INDEX inventory_transaction_to_idx ON inventory_transaction (to_storage_location_id);
CREATE INDEX inventory_transaction_date_idx ON inventory_transaction (txn_date);

-- Received at a storage location counts +, sent from it counts -.
CREATE VIEW stock_balance AS
SELECT row_number() OVER (ORDER BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id) AS row_id,
       storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id, sum(quantity) AS quantity
FROM (
    SELECT to_storage_location_id AS storage_location_id, to_sto_shed_id AS sto_shed_id,
           item_id, sub_cat_id, spec_id, status_id, quantity
    FROM inventory_transaction WHERE to_storage_location_id IS NOT NULL
    UNION ALL
    SELECT from_storage_location_id, from_sto_shed_id, item_id, sub_cat_id, spec_id, status_id, -quantity
    FROM inventory_transaction WHERE from_storage_location_id IS NOT NULL
) movement
GROUP BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id
HAVING sum(quantity) <> 0;
'''

OLD_TABLES = ('goods_receipt_detail', 'donation_detail', 'goods_receipt', 'donation', 'stock_transaction', 'stock',
              'purchase_order')


def fetch(cursor, sql):
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_pairs(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()


def clean(name):
    """Name with surrounding and doubled spaces removed."""
    return ' '.join((name or '').split())


def read_catalog():
    """
    {old item id: row} with cleaned names. Each item must be unique: one spelling, one category and one unit
    (names are compared ignoring case), and each sub category and spec one spelling.
    """
    with open(CATALOG, encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    catalog, problems = {}, []
    seen = {}  # lower-case key -> (field, value) first seen
    for row in rows:
        old_item_id = int(row['old_item_id'])
        if old_item_id in catalog:
            problems.append(f'old item {old_item_id} is listed twice')
        row = {key: clean(value) for key, value in row.items()}
        catalog[old_item_id] = row
        if row['category'] == 'DROP':
            continue
        if not row['item_name']:
            problems.append(f'old item {old_item_id} has no item_name')
            continue
        item = row['item_name'].lower()
        sub = row['sub_category'].lower()
        checks = [
            (('item', item), 'item_name', row['item_name']),
            (('item category', item), 'category', row['category']),
            (('item unit', item), 'unit', row['unit']),
        ]
        if sub:
            checks.append((('sub category', item, sub), 'sub_category', row['sub_category']))
        if row['spec']:
            checks.append((('spec', item, sub, row['spec'].lower()), 'spec', row['spec']))
        for key, field, value in checks:
            first = seen.setdefault(key, (old_item_id, value))
            if first[1] != value:
                problems.append(f'{row["item_name"]}: {field} is "{first[1]}" for old item {first[0]} '
                                f'but "{value}" for old item {old_item_id}')
    if problems:
        raise RuntimeError(f'{CATALOG.name} is not consistent:\n  ' + '\n  '.join(problems))
    return catalog


def po_type_and_status(po):
    """Purchase orders were used for every kind of receipt; the remarks tell which."""
    remarks = (po['remarks'] or '').strip()
    if remarks.startswith('TPV'):
        txn_type = OPENING_STOCK
    elif re.search(r'donation', remarks, re.I):
        txn_type = DONATION
    elif remarks.upper().startswith('NDMA'):
        txn_type = NDMA
    else:
        txn_type = PROCUREMENT
    status = NON_SERVICEABLE if re.search(r'expired|repair', remarks, re.I) else SERVICEABLE
    return txn_type, status


def rebuild(apps, schema_editor):
    catalog = read_catalog()
    with schema_editor.connection.cursor() as cursor:
        purchase_orders = fetch(cursor, 'SELECT * FROM purchase_order ORDER BY po_id')
        opening_stock = fetch(cursor, '''
            SELECT s.*, ss.sto_loc_id FROM stock s JOIN storage_shed ss ON ss.sto_shed_id = s.location_id
            WHERE s.source_type IS NULL ORDER BY s.stock_id
        ''')
        categories = dict(fetch_pairs(cursor, 'SELECT category_code, category_id FROM categories'))

        missing = {po['item_id'] for po in purchase_orders} | {row['item_id'] for row in opening_stock}
        missing -= set(catalog)
        if missing:
            raise RuntimeError(f'Items {sorted(missing)} are used but not in {CATALOG.name}.')

        for table in OLD_TABLES:
            cursor.execute(f'DROP TABLE {table}')
        cursor.execute('TRUNCATE items RESTART IDENTITY CASCADE')
        cursor.execute('CREATE UNIQUE INDEX items_name_unique ON items (lower(btrim("Item_name")))')

        # Units
        units = dict(fetch_pairs(cursor, 'SELECT unit_name, unit_id FROM units'))
        for name in sorted({row['unit'] for row in catalog.values() if row['unit']} - set(units)):
            cursor.execute('INSERT INTO units (unit_name, unit_symbol) VALUES (%s, %s) RETURNING unit_id', [name, name])
            units[name] = cursor.fetchone()[0]

        # Items, sub categories and specs, in category then name order
        items, sub_categories, specs = {}, {}, {}
        rows = sorted((row for row in catalog.values() if row['category'] != 'DROP'),
                      key=lambda row: (categories[row['category']], row['item_name'].lower()))
        for row in rows:
            name, sub, spec = row['item_name'], row['sub_category'] or None, row['spec'] or None
            if name not in items:
                cursor.execute(
                    'INSERT INTO items ("Item_name", item_category, unit_id, is_active) '
                    'VALUES (%s, %s, %s, true) RETURNING "Item_id"',
                    [name, categories[row['category']], units.get(row['unit'])],
                )
                items[name] = cursor.fetchone()[0]
            if sub and (name, sub) not in sub_categories:
                cursor.execute(
                    'INSERT INTO item_sub_category (item_id, sub_cat_name) VALUES (%s, %s) RETURNING sub_cat_id',
                    [items[name], sub],
                )
                sub_categories[name, sub] = cursor.fetchone()[0]
            if spec and (name, sub, spec) not in specs:
                cursor.execute(
                    'INSERT INTO item_spec (item_id, sub_cat_id, spec_name) VALUES (%s, %s, %s) RETURNING spec_id',
                    [items[name], sub_categories.get((name, sub)), spec],
                )
                specs[name, sub, spec] = cursor.fetchone()[0]

        def new_item(old_item_id):
            """(item_id, sub_cat_id, spec_id) for an old item, None if it is dropped."""
            row = catalog[old_item_id]
            if row['category'] == 'DROP':
                return None
            name, sub, spec = row['item_name'], row['sub_category'] or None, row['spec'] or None
            return items[name], sub_categories.get((name, sub)), specs.get((name, sub, spec))

        insert = '''
            INSERT INTO inventory_transaction (
                txn_no, txn_type_id, txn_date, item_id, sub_cat_id, spec_id, status_id, quantity, unit_price,
                to_storage_location_id, to_sto_shed_id, supplier_id, invoice_no, invoice_date,
                manufacturing_date, expiry_date, remarks, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        for row in opening_stock:
            target = new_item(row['item_id'])
            if target is None:
                continue
            cursor.execute(insert, [
                None, OPENING_STOCK, row['updated_at'].date(), *target, row['status_id'], row['quantity'], None,
                row['sto_loc_id'], row['location_id'], None, None, None, None, None,
                f'Opening stock as of {row["updated_at"]:%Y-%m-%d}', None, row['updated_at'],
            ])
        for po in purchase_orders:
            target = new_item(po['item_id'])
            if target is None:
                continue
            txn_type, status = po_type_and_status(po)
            created_at = po['created_at']
            txn_date = po['received_date'] or po['proc_date'] or po['invoice_date'] or created_at.date()
            cursor.execute(insert, [
                po['po_number'], txn_type, txn_date, *target, status, po['quantity'], po['unit_price'],
                po['location_id'], po['sto_shed_id'], po['supplier_id'], po['invoice_no'], po['invoice_date'],
                po['manufacturing_date'], po['expiry_date'], po['remarks'], po['created_by'], created_at,
            ])

        cursor.execute('ALTER TABLE items ADD CONSTRAINT items_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES units (unit_id)')


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0007_userprofile_all_areas_role'),
    ]

    operations = [
        migrations.RunSQL(SCHEMA_SQL),
        migrations.RunPython(rebuild),
        migrations.CreateModel(
            name='InventoryTransaction',
            fields=[
                ('txn_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('txn_no', models.CharField(blank=True, max_length=50, null=True)),
                ('txn_date', models.DateField()),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=15)),
                ('unit_price', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('issued_to', models.TextField(blank=True, null=True)),
                ('invoice_no', models.CharField(blank=True, max_length=100, null=True)),
                ('invoice_date', models.DateField(blank=True, null=True)),
                ('batch_no', models.CharField(blank=True, max_length=100, null=True)),
                ('manufacturing_date', models.DateField(blank=True, null=True)),
                ('expiry_date', models.DateField(blank=True, null=True)),
                ('remarks', models.TextField(blank=True, null=True)),
                ('created_by', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'inventory_transaction',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ItemSpec',
            fields=[
                ('spec_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('spec_name', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'item_spec',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ItemSubCategory',
            fields=[
                ('sub_cat_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('sub_cat_name', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'item_sub_category',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='StockBalance',
            fields=[
                ('row_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=20)),
            ],
            options={
                'db_table': 'stock_balance',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='TransactionType',
            fields=[
                ('type_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('type_name', models.CharField(max_length=50, unique=True)),
                ('direction', models.CharField(choices=[('in', 'Incoming'), ('out', 'Outgoing'), ('transfer', 'Transfer')], max_length=10)),
            ],
            options={
                'db_table': 'transaction_type',
                'managed': False,
            },
        ),
        migrations.DeleteModel(
            name='Donation',
        ),
        migrations.DeleteModel(
            name='GoodsReceipt',
        ),
        migrations.DeleteModel(
            name='PurchaseOrder',
        ),
        migrations.DeleteModel(
            name='Stock',
        ),
        migrations.DeleteModel(
            name='StockTransaction',
        ),
    ]
