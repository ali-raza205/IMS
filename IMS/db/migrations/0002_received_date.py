# purchase_order and donation are unmanaged tables, so the columns are added with SQL.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'ALTER TABLE purchase_order ADD COLUMN IF NOT EXISTS received_date date;',
                'ALTER TABLE donation ADD COLUMN IF NOT EXISTS received_date date;',
            ],
            reverse_sql=[
                'ALTER TABLE purchase_order DROP COLUMN IF EXISTS received_date;',
                'ALTER TABLE donation DROP COLUMN IF EXISTS received_date;',
            ],
        ),
    ]
