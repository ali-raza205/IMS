# Status is Serviceable or Non Serviceable; under it, a condition (Ready to Use; Repairable, Expired, Beyond Repair),
# like sub categories under items. Stock is kept per status and condition. Status 3 (Repairable) becomes
# Non Serviceable / Repairable. Each transaction can also record the shelf life of its items in months.

from django.db import migrations, models

SERVICEABLE, NON_SERVICEABLE, REPAIRABLE_STATUS = 1, 2, 3
READY, REPAIRABLE, EXPIRED, BEYOND_REPAIR = 1, 2, 3, 4

VIEW = '''
DROP VIEW stock_balance;
CREATE VIEW stock_balance AS
SELECT row_number() OVER (ORDER BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{c}, owner_id)
           AS row_id,
       storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{c}, owner_id, sum(quantity) AS quantity
FROM (
    SELECT to_storage_location_id AS storage_location_id, to_sto_shed_id AS sto_shed_id,
           item_id, sub_cat_id, spec_id, status_id{c}, owner_id, quantity
    FROM inventory_transaction WHERE to_storage_location_id IS NOT NULL AND approval_status = 'approved'
    UNION ALL
    SELECT from_storage_location_id, from_sto_shed_id, item_id, sub_cat_id, spec_id,
           coalesce(from_status_id, status_id){from_c}, coalesce(from_owner_id, owner_id), -quantity
    FROM inventory_transaction WHERE from_storage_location_id IS NOT NULL AND approval_status = 'approved'
) movement
GROUP BY storage_location_id, sto_shed_id, item_id, sub_cat_id, spec_id, status_id{c}, owner_id
HAVING sum(quantity) <> 0;
'''

SQL = f'''
CREATE TABLE item_condition (
    condition_id bigserial PRIMARY KEY,
    condition_name varchar(100) NOT NULL,
    status_id bigint NOT NULL REFERENCES item_status (status_id),
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (condition_id, status_id)
);
CREATE UNIQUE INDEX item_condition_name_unique ON item_condition (status_id, lower(btrim(condition_name)));
INSERT INTO item_condition (condition_id, condition_name, status_id) VALUES
    ({READY}, 'Ready to Use', {SERVICEABLE}),
    ({REPAIRABLE}, 'Repairable', {NON_SERVICEABLE}),
    ({EXPIRED}, 'Expired', {NON_SERVICEABLE}),
    ({BEYOND_REPAIR}, 'Beyond Repair', {NON_SERVICEABLE});
SELECT setval(pg_get_serial_sequence('item_condition', 'condition_id'), {BEYOND_REPAIR});

ALTER TABLE inventory_transaction
    ADD COLUMN condition_id bigint REFERENCES item_condition (condition_id),
    ADD COLUMN from_condition_id bigint REFERENCES item_condition (condition_id),
    ADD COLUMN shelf_life_months integer CHECK (shelf_life_months > 0);

-- Status 3 (Repairable) is Non Serviceable / Repairable now.
UPDATE inventory_transaction SET status_id = {NON_SERVICEABLE}, condition_id = {REPAIRABLE} WHERE status_id = {REPAIRABLE_STATUS};
UPDATE inventory_transaction SET from_status_id = {NON_SERVICEABLE}, from_condition_id = {REPAIRABLE}
    WHERE from_status_id = {REPAIRABLE_STATUS};
UPDATE inventory_transaction SET condition_id = {READY} WHERE condition_id IS NULL AND status_id = {SERVICEABLE};
UPDATE inventory_transaction SET condition_id = CASE WHEN remarks ~* 'expired' THEN {EXPIRED} ELSE {REPAIRABLE} END
    WHERE condition_id IS NULL AND status_id = {NON_SERVICEABLE};
UPDATE inventory_transaction SET from_condition_id = CASE WHEN from_status_id = {SERVICEABLE} THEN {READY} ELSE {REPAIRABLE} END
    WHERE from_status_id IS NOT NULL AND from_condition_id IS NULL;
DELETE FROM item_status WHERE status_id = {REPAIRABLE_STATUS};

ALTER TABLE inventory_transaction
    ALTER COLUMN condition_id SET NOT NULL,
    -- A condition belongs to its status.
    ADD CONSTRAINT inventory_transaction_condition_status_fkey
        FOREIGN KEY (condition_id, status_id) REFERENCES item_condition (condition_id, status_id),
    ADD CONSTRAINT inventory_transaction_from_condition_status_fkey
        FOREIGN KEY (from_condition_id, from_status_id) REFERENCES item_condition (condition_id, status_id);
''' + VIEW.format(c=', condition_id', from_c=', coalesce(from_condition_id, condition_id)')

REVERSE_SQL = VIEW.format(c='', from_c='') + f'''
ALTER TABLE inventory_transaction
    DROP CONSTRAINT inventory_transaction_condition_status_fkey,
    DROP CONSTRAINT inventory_transaction_from_condition_status_fkey;
INSERT INTO item_status (status_id, status_name) SELECT {REPAIRABLE_STATUS}, 'Repairable'
    WHERE NOT EXISTS (SELECT 1 FROM item_status WHERE status_id = {REPAIRABLE_STATUS});
UPDATE inventory_transaction SET status_id = {REPAIRABLE_STATUS} WHERE condition_id = {REPAIRABLE};
UPDATE inventory_transaction SET from_status_id = {REPAIRABLE_STATUS} WHERE from_condition_id = {REPAIRABLE};
ALTER TABLE inventory_transaction
    DROP COLUMN condition_id, DROP COLUMN from_condition_id, DROP COLUMN shelf_life_months;
DROP TABLE item_condition;
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0015_general_dispatch'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.CreateModel(
            name='ItemCondition',
            fields=[
                ('condition_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('condition_name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'item_condition',
                'managed': False,
            },
        ),
    ]
