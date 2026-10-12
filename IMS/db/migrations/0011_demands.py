# Demands: users request items for a storage location; the PDMA Admin (or a storage location approver for their
# own stock) approves each line, possibly for less (rationalized) and split over storage locations (allocations);
# the giving storage location issues them as transfers linked to the allocation.
# Also adds the "Storage location approver" role.

from django.db import migrations, models

SQL = '''
CREATE TABLE demand (
    demand_id bigserial PRIMARY KEY,
    demand_no varchar(30) UNIQUE,
    demand_date date NOT NULL,
    for_storage_location_id bigint NOT NULL REFERENCES storage_location (st_loc_id),
    purpose text,
    needed_by date,
    remarks text,
    created_by bigint,
    created_at timestamp
);
CREATE INDEX demand_for_idx ON demand (for_storage_location_id);

CREATE TABLE demand_line (
    line_id bigserial PRIMARY KEY,
    demand_id bigint NOT NULL REFERENCES demand (demand_id) ON DELETE CASCADE,
    item_id bigint NOT NULL REFERENCES items ("Item_id"),
    sub_cat_id bigint REFERENCES item_sub_category (sub_cat_id),
    spec_id bigint REFERENCES item_spec (spec_id),
    quantity numeric(15, 2) NOT NULL CHECK (quantity > 0),
    remarks text,
    referred_to_id bigint REFERENCES storage_location (st_loc_id),
    status varchar(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decision_remarks text,
    decided_by bigint,
    decided_at timestamp
);
CREATE INDEX demand_line_demand_idx ON demand_line (demand_id);
CREATE INDEX demand_line_referred_idx ON demand_line (referred_to_id);

CREATE TABLE demand_allocation (
    allocation_id bigserial PRIMARY KEY,
    line_id bigint NOT NULL REFERENCES demand_line (line_id) ON DELETE CASCADE,
    from_storage_location_id bigint NOT NULL REFERENCES storage_location (st_loc_id),
    quantity numeric(15, 2) NOT NULL CHECK (quantity > 0),
    approved_by bigint,
    approved_at timestamp,
    UNIQUE (line_id, from_storage_location_id)
);
CREATE INDEX demand_allocation_from_idx ON demand_allocation (from_storage_location_id);

ALTER TABLE inventory_transaction
    ADD COLUMN demand_allocation_id bigint REFERENCES demand_allocation (allocation_id);
CREATE INDEX inventory_transaction_allocation_idx ON inventory_transaction (demand_allocation_id);
'''

REVERSE_SQL = '''
ALTER TABLE inventory_transaction DROP COLUMN demand_allocation_id;
DROP TABLE demand_allocation;
DROP TABLE demand_line;
DROP TABLE demand;
'''


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0010_transaction_picture_receipt'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
        migrations.CreateModel(
            name='Demand',
            fields=[
                ('demand_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('demand_no', models.CharField(blank=True, max_length=30, null=True, unique=True)),
                ('demand_date', models.DateField()),
                ('purpose', models.TextField(blank=True, null=True)),
                ('needed_by', models.DateField(blank=True, null=True)),
                ('remarks', models.TextField(blank=True, null=True)),
                ('created_by', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'demand',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='DemandAllocation',
            fields=[
                ('allocation_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=15)),
                ('approved_by', models.BigIntegerField(blank=True, null=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'demand_allocation',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='DemandLine',
            fields=[
                ('line_id', models.BigAutoField(primary_key=True, serialize=False)),
                ('quantity', models.DecimalField(decimal_places=2, max_digits=15)),
                ('remarks', models.TextField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('decision_remarks', models.TextField(blank=True, null=True)),
                ('decided_by', models.BigIntegerField(blank=True, null=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'demand_line',
                'managed': False,
            },
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(choices=[('master', 'Master'), ('all_areas', 'All areas user'), ('location', 'Storage location user'), ('location_approver', 'Storage location approver')], default='location', max_length=20),
        ),
    ]
