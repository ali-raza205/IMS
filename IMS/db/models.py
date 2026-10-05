# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Categories(models.Model):
    category_id = models.BigAutoField(primary_key=True)
    category_code = models.TextField(blank=True, null=True)
    category_name = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'categories'


class Donation(models.Model):
    donation_id = models.BigAutoField(primary_key=True)
    donation_no = models.CharField(unique=True, max_length=50)
    donor = models.ForeignKey('Donors', models.DO_NOTHING)
    donation_date = models.DateField()
    storage_location = models.ForeignKey('StorageLocation', models.DO_NOTHING, db_column='warehouse_id')
    reference_no = models.CharField(max_length=100, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    item = models.ForeignKey('Items', models.DO_NOTHING)
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    estimated_unit_value = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    batch_no = models.CharField(max_length=100, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    sto_shed = models.ForeignKey('StorageShed', models.DO_NOTHING, blank=True, null=True)
    received_date = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'donation'


class Donors(models.Model):
    donor_id = models.BigAutoField(primary_key=True)
    donor_name = models.CharField(max_length=200)
    donor_type = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    active = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'donors'


class GoodsReceipt(models.Model):
    grn_id = models.BigAutoField(primary_key=True)
    po = models.ForeignKey('PurchaseOrder', models.DO_NOTHING)
    grn_no = models.CharField(unique=True, max_length=50, blank=True, null=True)
    receipt_date = models.DateField()
    received_by = models.BigIntegerField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    item = models.ForeignKey('Items', models.DO_NOTHING)
    received_quantity = models.DecimalField(max_digits=15, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    batch_no = models.CharField(max_length=100, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    sto_shed = models.ForeignKey('StorageShed', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'goods_receipt'


class ItemStatus(models.Model):
    status_id = models.BigAutoField(primary_key=True)
    status_name = models.TextField()

    class Meta:
        managed = False
        db_table = 'item_status'


class Items(models.Model):
    item_id = models.BigAutoField(db_column='Item_id', primary_key=True)  # Field name made lowercase.
    item_name = models.TextField(db_column='Item_name')  # Field name made lowercase.
    item_description = models.TextField(db_column='Item_description', blank=True, null=True)  # Field name made lowercase.
    item_category = models.ForeignKey(Categories, models.DO_NOTHING, db_column='item_category', blank=True, null=True)
    item_code = models.CharField(unique=True, max_length=50, blank=True, null=True)
    unit_id = models.BigIntegerField(blank=True, null=True)
    barcode = models.CharField(max_length=100, blank=True, null=True)
    # DB columns are unbounded numeric; these sizes only control API formatting/validation.
    minimum_stock = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    reorder_level = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    maximum_stock = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    is_perishable = models.BooleanField(blank=True, null=True)
    is_active = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'items'


class Locations(models.Model):
    location_id = models.BigAutoField(primary_key=True)
    location_name = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'locations'

    def __str__(self):
        return self.location_name or f'Location {self.location_id}'


class PurchaseOrder(models.Model):
    po_id = models.BigAutoField(primary_key=True)
    proc_date = models.DateField(blank=True, null=True)
    storage_location = models.ForeignKey('StorageLocation', models.DO_NOTHING, db_column='location_id', blank=True, null=True)
    po_number = models.CharField(unique=True, max_length=50, blank=True, null=True)
    supplier = models.ForeignKey('Suppliers', models.DO_NOTHING, blank=True, null=True)
    invoice_no = models.CharField(max_length=100, blank=True, null=True)
    invoice_date = models.DateField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    item = models.ForeignKey(Items, models.DO_NOTHING)
    quantity = models.DecimalField(max_digits=10, decimal_places=0)
    unit_price = models.FloatField()
    details = models.CharField(blank=True, null=True)
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    sto_shed = models.ForeignKey('StorageShed', models.DO_NOTHING, blank=True, null=True)
    received_date = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'purchase_order'


class Shed(models.Model):
    shed_id = models.BigAutoField(primary_key=True)
    shed_name = models.TextField()

    class Meta:
        managed = False
        db_table = 'shed'


class Stock(models.Model):
    item = models.ForeignKey(Items, models.DO_NOTHING)
    location = models.ForeignKey('StorageShed', models.DO_NOTHING)
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    unit = models.TextField()
    status = models.ForeignKey(ItemStatus, models.DO_NOTHING)
    stock_id = models.BigAutoField(primary_key=True)
    batch_id = models.BigIntegerField(blank=True, null=True)
    bin_id = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    source_type = models.CharField(max_length=20, blank=True, null=True)
    source_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'stock'
        unique_together = (('item', 'location'),)


class StockTransaction(models.Model):
    transection_id = models.BigAutoField(primary_key=True)
    stock = models.ForeignKey(Stock, models.DO_NOTHING)
    # storage_location ids (st_loc_id)
    from_warehouse = models.BigIntegerField()
    to_warehouse = models.BigIntegerField()
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    issue_date = models.DateField()
    reciving_date = models.DateField()
    note = models.TextField(blank=True, null=True)
    image_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'stock_transaction'


class StorageLocation(models.Model):
    """A warehouse. `location` is the area (district) it is established in."""
    st_loc_id = models.BigAutoField(primary_key=True)
    location = models.ForeignKey(Locations, models.DO_NOTHING)
    type = models.ForeignKey('StorageType', models.DO_NOTHING)
    details = models.TextField(blank=True, null=True)
    lat = models.DecimalField(max_digits=20, decimal_places=10, blank=True, null=True)
    long = models.DecimalField(max_digits=20, decimal_places=10, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'storage_location'

    def __str__(self):
        return self.details or f'Storage location {self.st_loc_id}'


class StorageShed(models.Model):
    sto_shed_id = models.BigAutoField(primary_key=True)
    sto_loc = models.ForeignKey(StorageLocation, models.DO_NOTHING, blank=True, null=True)
    shed = models.ForeignKey(Shed, models.DO_NOTHING, blank=True, null=True)
    details = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'storage_shed'


class StorageType(models.Model):
    type_id = models.BigAutoField(primary_key=True)
    type_name = models.TextField()

    class Meta:
        managed = False
        db_table = 'storage_type'


class Suppliers(models.Model):
    supplier_id = models.BigAutoField(primary_key=True)
    supplier_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    ntn = models.CharField(max_length=50, blank=True, null=True)
    gst = models.CharField(max_length=50, blank=True, null=True)
    active = models.BooleanField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'suppliers'


class Units(models.Model):
    unit_id = models.BigAutoField(primary_key=True)
    unit_name = models.CharField(max_length=50)
    unit_symbol = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'units'


class UserProfile(models.Model):
    """
    Ties a login to a storage location. Master users (and superusers) see every storage location.
    All areas users work on records of every storage location but, unlike master users,
    cannot edit or delete shared lookup data or change areas and storage locations.
    """
    ROLE_MASTER = 'master'
    ROLE_ALL_AREAS = 'all_areas'
    ROLE_LOCATION = 'location'
    ROLE_CHOICES = [
        (ROLE_MASTER, 'Master'),
        (ROLE_ALL_AREAS, 'All areas user'),
        (ROLE_LOCATION, 'Storage location user'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_LOCATION)
    storage_location = models.ForeignKey(
        StorageLocation, models.PROTECT, db_column='Sto_location_id', blank=True, null=True, related_name='users'
    )

    class Meta:
        db_table = 'user_profile'

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'

    def clean(self):
        # Without a storage location a non-master user sees no records at all.
        if self.role == self.ROLE_LOCATION and self.storage_location_id is None:
            raise ValidationError({'storage_location': 'Storage location users need a storage location.'})
