from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .models import (
    InventoryTransaction,
    StockBalance,
    StockOwner,
    StorageLocation,
    StorageShed,
    StorageType,
    TransactionType,
    UserProfile,
)

# ORM path(s) from each storage-location-bound model to its StorageLocation row.
# A record with several paths belongs to each of those storage locations.
LOCATION_LOOKUPS = {
    StorageLocation: ('pk',),
    StorageShed: ('sto_loc',),
    StockBalance: ('storage_location',),
    InventoryTransaction: ('from_storage_location', 'to_storage_location'),
}


def ndma_q(model):
    """
    What NDMA users see of `model`: NDMA's own stock and its transactions, in every storage location (and the storage
    locations and sheds to keep it in). None when NDMA sees nothing of it.
    """
    return {
        StorageLocation: Q(),
        StorageShed: Q(),
        StockBalance: Q(owner=StockOwner.NDMA),
        InventoryTransaction: Q(owner=StockOwner.NDMA) | Q(from_owner=StockOwner.NDMA),
    }.get(model)


def inspection_q(model):
    """What the inspection team sees of `model`: all stock and the status changes it approves."""
    return {
        StorageLocation: Q(),
        StorageShed: Q(),
        StockBalance: Q(),
        InventoryTransaction: Q(txn_type=TransactionType.STATUS_CHANGE),
    }.get(model)


def role_scope(user, model):
    """
    (True, Q or None) for roles that see by what, not where: NDMA (its own stock) and the inspection team (status
    changes); None means nothing of `model`. (False, None) for everyone else.
    """
    if is_ndma(user):
        return True, ndma_q(model)
    if is_inspector(user):
        return True, inspection_q(model)
    return False, None


def location_q(model, location_id):
    """Rows of `model` that belong to storage location `location_id`."""
    q = Q()
    for lookup in LOCATION_LOOKUPS[model]:
        q |= Q(**{lookup: location_id})
    return q


def is_master(user):
    """Superusers and users with the master role (PDMA Admin); only they edit lookup data, areas and storage locations."""
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == UserProfile.ROLE_MASTER


def is_ndma(user):
    """
    NDMA users (a separate body): see and record only NDMA's own stock, in any storage location, and alone decide
    the demand lines referred to NDMA.
    """
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == UserProfile.ROLE_NDMA


def is_inspector(user):
    """The inspection team approves or rejects status changes (e.g. Serviceable to Repairable)."""
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == UserProfile.ROLE_INSPECTION


def is_district(location):
    """Districts manage their own stock; warehouses' movements need DG PDMA approval."""
    return location is not None and location.type_id == StorageType.DISTRICT


def is_pdma_admin(user):
    """The PDMA Admin (master users and superusers): refers every demand and decides it from PDMA stock."""
    return is_master(user)


def sees_all_locations(user):
    """Master and all areas users see and change records of every storage location."""
    if is_master(user):
        return True
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == UserProfile.ROLE_ALL_AREAS


def can_decide_demand_line(user, line):
    """
    Who accepts, rejects or rationalizes a demand line: NDMA alone when it is referred to NDMA (NDMA stock); the
    district itself when it is referred to a district (a return the DG asks for: district stock is the district's);
    otherwise the PDMA Admin. Warehouses only issue.
    """
    if line.referred_owner_id == StockOwner.NDMA:
        return is_ndma(user)
    if is_district(line.referred_to):
        return not sees_all_locations(user) and not role_scope(user, InventoryTransaction)[0]             and user_location_id(user) == line.referred_to_id
    return is_pdma_admin(user)


def user_location_id(user):
    """The user's storage location id (st_loc_id)."""
    profile = getattr(user, 'profile', None)
    return profile.storage_location_id if profile else None


def limit_to_location(queryset, user):
    """Rows of a storage-location-bound model that belong to the user's storage location (all rows for master and all areas users)."""
    if queryset.model not in LOCATION_LOOKUPS or sees_all_locations(user):
        return queryset
    special, q = role_scope(user, queryset.model)
    if special:
        return queryset.none() if q is None else queryset.filter(q)
    location_id = user_location_id(user)
    if location_id is None:
        return queryset.none()
    return queryset.filter(location_q(queryset.model, location_id))


class IsMasterOrReadOnly(permissions.BasePermission):
    """Any logged-in user can read; only master users can write."""

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or is_master(request.user)


class IsMasterOrCreateOnly(permissions.BasePermission):
    """Any logged-in user can read and add; only master users can edit or delete."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS or request.method == 'POST':
            return True
        return is_master(request.user)


class LocationScopedFieldsMixin:
    """
    Serializer mixin: dropdown (related) fields only accept records of the user's storage location,
    e.g. a transaction can only pick that storage location's sheds. `unscoped_fields` are left open.
    """
    unscoped_fields = ()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request is None:
            return fields
        for name, field in fields.items():
            if name in self.unscoped_fields:
                continue
            field = getattr(field, 'child_relation', field)
            if getattr(field, 'queryset', None) is not None:
                field.queryset = limit_to_location(field.queryset, request.user)
                if field.queryset.model in LOCATION_LOOKUPS and not sees_all_locations(request.user):
                    field.error_messages['does_not_exist'] = (
                        '"{pk_value}" does not exist or is not in your storage location.'
                    )
        return fields


class LocationScopedMixin:
    """
    Limits a viewset to the logged-in user's storage location; master and all areas users see everything.
    The storage location paths come from LOCATION_LOOKUPS.
    Saves that would put a record outside the user's storage location are rolled back.
    `created_by_field` is filled with the logged-in user's id on create.
    """
    created_by_field = None

    def scope_filter(self, location_id):
        """Records the user may see."""
        return location_q(self.queryset.model, location_id)

    def write_filter(self, location_id):
        """Records the user may create, edit or delete."""
        return self.scope_filter(location_id)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if sees_all_locations(user):
            return queryset
        special, q = role_scope(user, queryset.model)
        if special:
            return queryset.none() if q is None else queryset.filter(q)
        location_id = user_location_id(user)
        if location_id is None:
            return queryset.none()
        return queryset.filter(self.scope_filter(location_id))

    def _check_writable(self, instance):
        user = self.request.user
        if sees_all_locations(user):
            return
        if is_inspector(user):
            raise PermissionDenied('The inspection team approves status changes; it does not record movements.')
        if is_ndma(user):
            q = ndma_q(type(instance))
            if q is None or not type(instance).objects.filter(q, pk=instance.pk).exists():
                raise PermissionDenied('NDMA can only change records of NDMA stock.')
            return
        location_id = user_location_id(user)
        writable = location_id is not None and type(instance).objects.filter(
            self.write_filter(location_id), pk=instance.pk
        ).exists()
        if not writable:
            raise PermissionDenied('You can only change records of your own storage location.')

    def _save_checked(self, serializer, **extra):
        # Save first so the storage location can be followed through related records, then undo if out of scope.
        with transaction.atomic():
            saved = serializer.save(**extra)
            for instance in saved if isinstance(saved, list) else [saved]:
                self._check_writable(instance)

    def perform_create(self, serializer):
        extra = {}
        if self.created_by_field:
            extra[self.created_by_field] = self.request.user.id
            model = getattr(serializer, 'child', serializer).Meta.model  # a list of records has a child serializer
            if hasattr(model, 'created_at'):
                extra['created_at'] = timezone.now()
        self._save_checked(serializer, **extra)

    def perform_update(self, serializer):
        self._save_checked(serializer)

    def perform_destroy(self, instance):
        self._check_writable(instance)
        instance.delete()
