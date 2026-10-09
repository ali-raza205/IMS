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


class ItemStatus(models.Model):
    """Serviceable (1) or Non Serviceable (2)."""
    SERVICEABLE = 1
    NON_SERVICEABLE = 2

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
    unit = models.ForeignKey('Units', models.DO_NOTHING, blank=True, null=True)
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


class ItemSubCategory(models.Model):
    """A kind of an item, e.g. Boat -> Inflatable / Fiberglass."""
    sub_cat_id = models.BigAutoField(primary_key=True)
    item = models.ForeignKey(Items, models.DO_NOTHING, related_name='sub_categories')
    sub_cat_name = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'item_sub_category'


class ItemSpec(models.Model):
    """
    A size, capacity or power of an item, e.g. Boat -> 19 ft.
    With a sub category it only applies to that sub category (Fiberglass -> 19 ft), without one to the whole item.
    """
    spec_id = models.BigAutoField(primary_key=True)
    item = models.ForeignKey(Items, models.DO_NOTHING, related_name='specs')
    sub_cat = models.ForeignKey(ItemSubCategory, models.DO_NOTHING, blank=True, null=True, related_name='specs')
    spec_name = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'item_spec'


class TransactionType(models.Model):
    """
    Donation, Procurement, NDMA and Opening Stock bring stock in, Dispatch takes it out,
    Internal Transfer moves it from one storage location to another.
    """
    IN = 'in'
    OUT = 'out'
    TRANSFER = 'transfer'
    DIRECTION_CHOICES = [(IN, 'Incoming'), (OUT, 'Outgoing'), (TRANSFER, 'Transfer')]

    # type_id of the rows added by migration 0008
    DONATION = 1
    PROCUREMENT = 2
    NDMA = 3
    DISPATCH = 4
    INTERNAL_TRANSFER = 5
    OPENING_STOCK = 6

    type_id = models.BigAutoField(primary_key=True)
    type_name = models.CharField(unique=True, max_length=50)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)

    class Meta:
        managed = False
        db_table = 'transaction_type'

    def __str__(self):
        return self.type_name


class Party(models.Model):
    """
    Who stock comes from (or goes to) outside the storage locations, under the transaction type it belongs to:
    suppliers under Procurement, donors under Donation, NDMA under NDMA.
    """
    party_id = models.BigAutoField(primary_key=True)
    party_name = models.TextField()
    txn_type = models.ForeignKey(TransactionType, models.DO_NOTHING, related_name='parties')
    contact_person = models.TextField(blank=True, null=True)
    phone = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    ntn = models.TextField(blank=True, null=True)
    gst = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'party'

    def __str__(self):
        return self.party_name


class InventoryTransaction(models.Model):
    """
    Every incoming and outgoing movement, one item line per row.
    Incoming rows fill the `to_` storage location, outgoing rows the `from_` one, transfers both.
    """
    txn_id = models.BigAutoField(primary_key=True)
    txn_no = models.CharField(max_length=50, blank=True, null=True)
    txn_type = models.ForeignKey(TransactionType, models.DO_NOTHING)
    txn_date = models.DateField()
    item = models.ForeignKey(Items, models.DO_NOTHING)
    sub_cat = models.ForeignKey(ItemSubCategory, models.DO_NOTHING, blank=True, null=True)
    spec = models.ForeignKey(ItemSpec, models.DO_NOTHING, blank=True, null=True)
    status = models.ForeignKey(ItemStatus, models.DO_NOTHING, default=ItemStatus.SERVICEABLE)
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    from_storage_location = models.ForeignKey(
        'StorageLocation', models.DO_NOTHING, blank=True, null=True, related_name='outgoing_transactions'
    )
    from_sto_shed = models.ForeignKey(
        'StorageShed', models.DO_NOTHING, blank=True, null=True, related_name='outgoing_transactions'
    )
    to_storage_location = models.ForeignKey(
        'StorageLocation', models.DO_NOTHING, blank=True, null=True, related_name='incoming_transactions'
    )
    to_sto_shed = models.ForeignKey(
        'StorageShed', models.DO_NOTHING, blank=True, null=True, related_name='incoming_transactions'
    )
    party = models.ForeignKey('Party', models.DO_NOTHING, blank=True, null=True)
    issued_to = models.TextField(blank=True, null=True)
    invoice_no = models.CharField(max_length=100, blank=True, null=True)
    invoice_date = models.DateField(blank=True, null=True)
    batch_no = models.CharField(max_length=100, blank=True, null=True)
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    picture = models.ImageField(upload_to='transactions/pictures/%Y/%m/', max_length=255, blank=True, null=True)
    receipt = models.ImageField(upload_to='transactions/receipts/%Y/%m/', max_length=255, blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'inventory_transaction'


class StockBalance(models.Model):
    """
    Read-only database view: quantity on hand per storage location, shed, item, sub category, spec and status,
    i.e. everything received there minus everything sent from there.
    """
    row_id = models.BigIntegerField(primary_key=True)
    storage_location = models.ForeignKey('StorageLocation', models.DO_NOTHING)
    sto_shed = models.ForeignKey('StorageShed', models.DO_NOTHING, blank=True, null=True)
    item = models.ForeignKey(Items, models.DO_NOTHING)
    sub_cat = models.ForeignKey(ItemSubCategory, models.DO_NOTHING, blank=True, null=True)
    spec = models.ForeignKey(ItemSpec, models.DO_NOTHING, blank=True, null=True)
    status = models.ForeignKey(ItemStatus, models.DO_NOTHING)
    quantity = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'stock_balance'


class Locations(models.Model):
    location_id = models.BigAutoField(primary_key=True)
    location_name = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'locations'

    def __str__(self):
        return self.location_name or f'Location {self.location_id}'


class Shed(models.Model):
    shed_id = models.BigAutoField(primary_key=True)
    shed_name = models.TextField()

    class Meta:
        managed = False
        db_table = 'shed'


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
