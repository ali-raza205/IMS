from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .models import (
    Donation,
    GoodsReceipt,
    Locations,
    PurchaseOrder,
    Stock,
    StorageLocation,
    StorageShed,
    UserProfile,
)

# ORM path from each location-bound model to its Locations row.
LOCATION_LOOKUPS = {
    Locations: 'pk',
    Donation: 'warehouse',
    PurchaseOrder: 'location',
    GoodsReceipt: 'po__location',
    StorageLocation: 'location',
    StorageShed: 'sto_loc__location',
    Stock: 'location__sto_loc__location',
}


def is_master(user):
    """Superusers and users with the master role see and edit every location."""
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    return profile is not None and profile.role == UserProfile.ROLE_MASTER


def user_location_id(user):
    profile = getattr(user, 'profile', None)
    return profile.location_id if profile else None


def limit_to_location(queryset, user):
    """Rows of a location-bound model that belong to the user's location (all rows for master users)."""
    lookup = LOCATION_LOOKUPS.get(queryset.model)
    if lookup is None or is_master(user):
        return queryset
    location_id = user_location_id(user)
    if location_id is None:
        return queryset.none()
    return queryset.filter(**{lookup: location_id})


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
    Serializer mixin: dropdown (related) fields only accept records of the user's location,
    e.g. a goods receipt can only pick that location's purchase orders.
    """

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request is None:
            return fields
        for field in fields.values():
            field = getattr(field, 'child_relation', field)
            if getattr(field, 'queryset', None) is not None:
                field.queryset = limit_to_location(field.queryset, request.user)
        return fields


class LocationScopedMixin:
    """
    Limits a viewset to the logged-in user's location; master users see everything.
    The location path comes from LOCATION_LOOKUPS unless `location_lookup` is set.
    Saves that would put a record outside the user's location are rolled back.
    `created_by_field` is filled with the logged-in user's id on create.
    """
    location_lookup = None
    created_by_field = None

    def scope_filter(self, location_id):
        """Records the user may see."""
        lookup = self.location_lookup or LOCATION_LOOKUPS[self.queryset.model]
        return Q(**{lookup: location_id})

    def write_filter(self, location_id):
        """Records the user may create, edit or delete."""
        return self.scope_filter(location_id)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if is_master(user):
            return queryset
        location_id = user_location_id(user)
        if location_id is None:
            return queryset.none()
        return queryset.filter(self.scope_filter(location_id))

    def _check_writable(self, instance):
        user = self.request.user
        if is_master(user):
            return
        location_id = user_location_id(user)
        writable = location_id is not None and type(instance).objects.filter(
            self.write_filter(location_id), pk=instance.pk
        ).exists()
        if not writable:
            raise PermissionDenied('You can only change records of your own location.')

    def _save_checked(self, serializer, **extra):
        # Save first so the location can be followed through related records, then undo if out of scope.
        with transaction.atomic():
            instance = serializer.save(**extra)
            self._check_writable(instance)

    def perform_create(self, serializer):
        extra = {}
        if self.created_by_field:
            extra[self.created_by_field] = self.request.user.id
            if hasattr(serializer.Meta.model, 'created_at'):
                extra['created_at'] = timezone.now()
        self._save_checked(serializer, **extra)

    def perform_update(self, serializer):
        self._save_checked(serializer)

    def perform_destroy(self, instance):
        self._check_writable(instance)
        instance.delete()
