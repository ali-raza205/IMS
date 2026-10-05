from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    """Role and storage location (warehouse) are set on the user's page in the admin."""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Role and storage location'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'storage_location':
            # Show the area next to each warehouse, e.g. "Lahore Warehouse (Lahore)".
            field = super().formfield_for_foreignkey(db_field, request, **kwargs)
            field.queryset = field.queryset.select_related('location').order_by('details')
            field.label_from_instance = lambda sl: f'{sl} ({sl.location.location_name})'
            return field
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class UserWithProfileAdmin(UserAdmin):
    inlines = [UserProfileInline]
    list_display = ('username', 'first_name', 'last_name', 'get_role', 'get_storage_location', 'is_active')
    list_filter = UserAdmin.list_filter + ('profile__role', 'profile__storage_location')
    list_select_related = ('profile__storage_location',)

    @admin.display(description='Role')
    def get_role(self, user):
        profile = getattr(user, 'profile', None)
        return profile.get_role_display() if profile else '-'

    @admin.display(description='Storage location')
    def get_storage_location(self, user):
        profile = getattr(user, 'profile', None)
        return str(profile.storage_location) if profile and profile.storage_location else '-'


admin.site.unregister(User)
admin.site.register(User, UserWithProfileAdmin)
