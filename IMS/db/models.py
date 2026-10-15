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
    """Serviceable (1) or Non Serviceable (2); the item's condition is the next level (ItemCondition)."""
    SERVICEABLE = 1
    NON_SERVICEABLE = 2

    status_id = models.BigAutoField(primary_key=True)
    status_name = models.TextField()

    class Meta:
        managed = False
        db_table = 'item_status'


class StockOwner(models.Model):
    """Who stock belongs to, wherever it is kept: PDMA (1) or NDMA (2)."""
    PDMA = 1
    NDMA = 2

    owner_id = models.BigAutoField(primary_key=True)
    owner_name = models.CharField(unique=True, max_length=50)

    class Meta:
        managed = False
        db_table = 'stock_owner'

    def __str__(self):
        return self.owner_name


class ItemCondition(models.Model):
    """
    The condition of stock under its status, like sub categories under items: Serviceable -> Ready to Use;
    Non Serviceable -> Repairable, Expired, Beyond Repair.
    """
    READY_TO_USE = 1
    REPAIRABLE = 2
    EXPIRED = 3
    BEYOND_REPAIR = 4

    condition_id = models.BigAutoField(primary_key=True)
    condition_name = models.CharField(max_length=100)
    status = models.ForeignKey(ItemStatus, models.DO_NOTHING, related_name='conditions')
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'item_condition'


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
    Donation, Procurement, NDMA and Opening Stock bring stock in. Dispatch sends it to a district or to a department,
    Internal Transfer shifts it between warehouses or sheds, Return sends it back (district to warehouse, PDMA to
    NDMA), Status Change moves it from one status to another (e.g. Serviceable to Repairable) at one location.
    """
    IN = 'in'
    OUT = 'out'
    TRANSFER = 'transfer'
    STATUS = 'status'
    DIRECTION_CHOICES = [(IN, 'Incoming'), (OUT, 'Outgoing'), (TRANSFER, 'Transfer'), (STATUS, 'Status change')]

    # type_id of the rows added by migration 0008
    DONATION = 1
    PROCUREMENT = 2
    NDMA = 3
    DISPATCH = 4
    INTERNAL_TRANSFER = 5
    OPENING_STOCK = 6
    STATUS_CHANGE = 7
    RETURN = 9

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


class DispatchPurpose(models.Model):
    """Why stock was dispatched for use: relief distribution, rescue operation..."""
    purpose_id = models.BigAutoField(primary_key=True)
    purpose_name = models.CharField(unique=True, max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'dispatch_purpose'


class InventoryTransaction(models.Model):
    """
    Every incoming and outgoing movement, one item line per row.
    Incoming rows fill the `to_` storage location, outgoing rows the `from_` one, transfers both.
    """
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    APPROVAL_CHOICES = [(PENDING, 'Pending'), (APPROVED, 'Approved'), (REJECTED, 'Rejected')]

    txn_id = models.BigAutoField(primary_key=True)
    txn_no = models.CharField(max_length=50, blank=True, null=True)
    txn_type = models.ForeignKey(TransactionType, models.DO_NOTHING)
    txn_date = models.DateField()
    item = models.ForeignKey(Items, models.DO_NOTHING)
    sub_cat = models.ForeignKey(ItemSubCategory, models.DO_NOTHING, blank=True, null=True)
    spec = models.ForeignKey(ItemSpec, models.DO_NOTHING, blank=True, null=True)
    status = models.ForeignKey(ItemStatus, models.DO_NOTHING, default=ItemStatus.SERVICEABLE)
    condition = models.ForeignKey(ItemCondition, models.DO_NOTHING, related_name='transactions')
    # Status Change only: the status and condition the stock had before; `status` and `condition` are the new ones.
    from_status = models.ForeignKey(
        ItemStatus, models.DO_NOTHING, blank=True, null=True, related_name='status_changes_from'
    )
    from_condition = models.ForeignKey(
        ItemCondition, models.DO_NOTHING, blank=True, null=True, related_name='status_changes_from'
    )
    # Whose stock this is (PDMA or NDMA); `from_owner` is the owner before when ownership changes hands.
    owner = models.ForeignKey(StockOwner, models.DO_NOTHING, default=StockOwner.PDMA, related_name='transactions')
    from_owner = models.ForeignKey(
        StockOwner, models.DO_NOTHING, blank=True, null=True, related_name='transactions_handed_over'
    )
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
    # How long the items keep, from manufacturing; sets `expiry_date` when that is not given.
    shelf_life_months = models.PositiveIntegerField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    purpose = models.ForeignKey(DispatchPurpose, models.DO_NOTHING, blank=True, null=True)
    # Pending movements count for nothing until approved: warehouse movements and returns by DG PDMA (master users),
    # status changes by the inspection team.
    approval_status = models.CharField(max_length=10, choices=APPROVAL_CHOICES, default=APPROVED)
    approved_by = models.BigIntegerField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approval_remarks = models.TextField(blank=True, null=True)
    demand_allocation = models.ForeignKey(
        'DemandAllocation', models.DO_NOTHING, blank=True, null=True, related_name='transactions'
    )
    picture = models.ImageField(upload_to='transactions/pictures/%Y/%m/', max_length=255, blank=True, null=True)
    receipt = models.ImageField(upload_to='transactions/receipts/%Y/%m/', max_length=255, blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'inventory_transaction'


class Demand(models.Model):
    """A request for items for a storage location; each item is a DemandLine."""
    demand_id = models.BigAutoField(primary_key=True)
    demand_no = models.CharField(unique=True, max_length=30, blank=True, null=True)
    demand_date = models.DateField()
    for_storage_location = models.ForeignKey('StorageLocation', models.DO_NOTHING, related_name='demands')
    purpose = models.TextField(blank=True, null=True)
    needed_by = models.DateField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'demand'


class DemandLine(models.Model):
    """
    One item of a demand. The PDMA Admin refers it to a storage location (`referred_to`) or requests it from NDMA
    (`referred_owner`); it is approved or rejected by the PDMA Admin (PDMA stock) or by NDMA (NDMA stock);
    an approval is one or more DemandAllocations, possibly less than requested (rationalized).
    """
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = [(PENDING, 'Pending'), (APPROVED, 'Approved'), (REJECTED, 'Rejected')]

    line_id = models.BigAutoField(primary_key=True)
    demand = models.ForeignKey(Demand, models.CASCADE, related_name='lines')
    item = models.ForeignKey(Items, models.DO_NOTHING)
    sub_cat = models.ForeignKey(ItemSubCategory, models.DO_NOTHING, blank=True, null=True)
    spec = models.ForeignKey(ItemSpec, models.DO_NOTHING, blank=True, null=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    remarks = models.TextField(blank=True, null=True)
    referred_to = models.ForeignKey(
        'StorageLocation', models.DO_NOTHING, blank=True, null=True, related_name='referred_demand_lines'
    )
    # Whose stock the line is to be given from: PDMA (decided by the PDMA Admin) or NDMA (decided by NDMA only).
    referred_owner = models.ForeignKey(
        'StockOwner', models.DO_NOTHING, default=1, related_name='referred_demand_lines'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    decision_remarks = models.TextField(blank=True, null=True)
    decided_by = models.BigIntegerField(blank=True, null=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'demand_line'


class DemandAllocation(models.Model):
    """Approved quantity of a demand line from one storage location; issued as transactions linked to it."""
    allocation_id = models.BigAutoField(primary_key=True)
    line = models.ForeignKey(DemandLine, models.CASCADE, related_name='allocations')
    from_storage_location = models.ForeignKey('StorageLocation', models.DO_NOTHING, related_name='demand_allocations')
    owner = models.ForeignKey(StockOwner, models.DO_NOTHING, default=StockOwner.PDMA, related_name='demand_allocations')
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    approved_by = models.BigIntegerField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'demand_allocation'


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
    condition = models.ForeignKey(ItemCondition, models.DO_NOTHING)
    owner = models.ForeignKey(StockOwner, models.DO_NOTHING)
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
    """District (1): manages its own stock. Warehouse (2): its movements need DG PDMA approval."""
    DISTRICT = 1
    WAREHOUSE = 2

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
    Inspection team users approve or reject status changes.
    Master users (PDMA Admin, DG PDMA) refer every demand and approve, reject or rationalize every line from PDMA stock;
    they request NDMA stock by referring a line to NDMA. NDMA users (a separate body) see and record only NDMA's own
    stock, kept in any storage location, and the lines referred to NDMA, which they alone decide.
    Storage locations only issue what was approved.
    """
    ROLE_NDMA = 'ndma'
    ROLE_MASTER = 'master'
    ROLE_ALL_AREAS = 'all_areas'
    ROLE_LOCATION = 'location'
    ROLE_INSPECTION = 'inspection'
    ROLE_CHOICES = [
        (ROLE_NDMA, 'NDMA'),
        (ROLE_MASTER, 'Master'),
        (ROLE_ALL_AREAS, 'All areas user'),
        (ROLE_LOCATION, 'Storage location user'),
        (ROLE_INSPECTION, 'Inspection team'),
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
