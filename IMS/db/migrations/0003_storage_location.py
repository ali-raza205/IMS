# Users, purchase orders and donations belong to a storage location (warehouse) instead of a location (area).
# purchase_order.location_id already references storage_location in the database.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0002_received_date'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name='userprofile', name='location'),
                migrations.AddField(
                    model_name='userprofile',
                    name='storage_location',
                    field=models.ForeignKey(
                        blank=True, null=True, db_column='Sto_location_id',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='users', to='db.storagelocation',
                    ),
                ),
            ],
            database_operations=[
                # No-op where the column was already switched by hand.
                migrations.RunSQL(
                    sql='''
                        DO $$
                        BEGIN
                            IF EXISTS (SELECT 1 FROM information_schema.columns
                                       WHERE table_name = 'user_profile' AND column_name = 'location_id') THEN
                                ALTER TABLE user_profile DROP COLUMN location_id;
                                ALTER TABLE user_profile ADD COLUMN "Sto_location_id" bigint
                                    REFERENCES storage_location (st_loc_id);
                            END IF;
                        END $$;
                    ''',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.RunSQL(
            sql=[
                'ALTER TABLE donation DROP CONSTRAINT IF EXISTS fk_donation_location;',
                'ALTER TABLE donation ADD CONSTRAINT fk_donation_storage_location '
                'FOREIGN KEY (warehouse_id) REFERENCES storage_location (st_loc_id);',
            ],
            reverse_sql=[
                'ALTER TABLE donation DROP CONSTRAINT IF EXISTS fk_donation_storage_location;',
                'ALTER TABLE donation ADD CONSTRAINT fk_donation_location '
                'FOREIGN KEY (warehouse_id) REFERENCES locations (location_id);',
            ],
        ),
    ]
