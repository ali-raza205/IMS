# A picture of the goods and a receipt image per transaction. The images are files under MEDIA_ROOT;
# the columns hold their path there.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('db', '0009_party'),
    ]

    operations = [
        migrations.RunSQL(
            sql='''
                ALTER TABLE inventory_transaction
                    ADD COLUMN picture varchar(255),
                    ADD COLUMN receipt varchar(255);
            ''',
            reverse_sql='''
                ALTER TABLE inventory_transaction DROP COLUMN picture, DROP COLUMN receipt;
            ''',
        ),
    ]
