# NDMA role and stock ownership.
#
# NDMA is a separate body: the PDMA Admin refers and decides demands from PDMA stock, and requests NDMA stock by
# referring a line to NDMA (demand_line.referred_owner_id); only NDMA accepts, rejects or rationalizes those lines.
# The storage location approver role is dropped: storage locations only issue what was approved.
# Stock in any storage location belongs to an owner (stock_owner: PDMA or NDMA). Every transaction has the owner
# of what it moves (owner_id; existing rows are PDMA's); from_owner_id is the owner before when ownership changes
# hands (e.g. NDMA stock issued to a PDMA district), like from_status_id for status. stock_balance is kept per owner.
# Demand allocations say whose stock is given.

from django.db import migrations, models

PDMA, NDMA = 1, 2

VIEW = '''
DROP VIEW stock_balance;
CREATE VIEW stock_balance AS
SELECT row_number() OVER (ORDER BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{owner})
           AS row_id,
       storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{owner}, sum(quantity) AS quantity
FROM (
    SELECT to_storage_location_id AS storage_location_id, to_sto_shed_id AS sto_shed_id,
           item_id, sub_cat_id, spec_id, status_id{owner}, quantity
    FROM inventory_transaction WHERE to_storage_location_id IS NOT NULL
    UNION ALL
    SELECT from_storage_location_id, from_sto_shed_id, item_id, sub_cat_id, spec_id,
           coalesce(from_status_id, status_id){from_owner}, -quantity
    FROM inventory_transaction WHERE from_storage_location_id IS NOT NULL
) movement
GROUP BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{owner}
HAVING sum(quantity) <> 0;
'''

SQL = f'''
CREATE TABLE stock_owner (
    owner_id bigserial PRIMARY KEY,
    owner_name varchar(50) NOT NULL UNIQUE
);
INSERT INTO stock_owner (owner_id, owner_name) VALUES ({PDMA}, 'PDMA'), ({NDMA}, 'NDMA');
SELECT setval(pg_get_serial_sequence('stock_owner', 'owner_id'), 2);

ALTER TABLE inventory_transaction
    ADD COLUMN owner_id bigint NOT NULL DEFAULT {PDMA} REFERENCES stock_owner (owner_id),
    ADD COLUMN from_owner_id bigint REFERENCES stock_owner (owner_id),
    ADD CONSTRAINT inventory_transaction_owner_change_check CHECK (from_owner_id IS NULL OR from_owner_id <> owner_id);
CREATE INDEX inventory_transaction_owner_idx ON inventory_transaction (owner_id);

ALTER TABLE demand_line
    ADD COLUMN referred_owner_id bigint NOT NULL DEFAULT {PDMA} REFERENCES stock_owner (owner_id);

ALTER TABLE demand_allocation
    ADD COLUMN owner_id bigint NOT NULL DEFAULT {PDMA} REFERENCES stock_owner (owner_id),
    DROP CONSTRAINT demand_allocation_line_id_from_storage_location_id_key,
    ADD CONSTRAINT demand_allocation_line_location_owner_key UNIQUE (line_id, from_storage_location_id, owner_id);
''' + VIEW.format(owner=', owner_id', from_owner=', coalesce(from_owner_id, owner_id)')

REVERSE_SQL = VIEW.format(owner='', from_owner='') + f'''
DELETE FROM demand_allocation WHERE owner_id <> {PDMA};
ALTER TABLE demand_allocation
    DROP CONSTRAINT demand_allocation_line_location_owner_key,
    DROP COLUMN owner_id,
    ADD CONSTRAINT demand_allocation_line_id_from_storage_location_id_key UNIQUE (line_id, from_storage_location_id);
ALTER TABLE inventory_transaction DROP COLUMN from_owner_id, DROP COLUMN owner_id;
ALTER TABLE demand_line DROP COLUMN referred_owner_id;
DROP TABLE stock_owner;
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0012_status_change'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(choices=[('ndma', 'NDMA'), ('master', 'Master'), ('all_areas', 'All areas user'), ('location', 'Storage location user')], default='location', max_length=20),
        ),
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.CreateModel(
            name='StockOwner',
            fields=[
                ('owner_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('owner_name', models.CharField(max_length=50, unique=True)),
            ],
            options={
                'db_table': 'stock_owner',
                'managed': False,
            },
        ),
    ]
