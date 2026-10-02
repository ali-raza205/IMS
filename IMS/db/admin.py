from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    """Role and location are set on the user's page in the admin."""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Role and location'


class UserWithProfileAdmin(UserAdmin):
    inlines = [UserProfileInline]
    list_display = ('username', 'first_name', 'last_name', 'get_role', 'get_location', 'is_active')

    @admin.display(description='Role')
    def get_role(self, user):
        profile = getattr(user, 'profile', None)
        return profile.get_role_display() if profile else '-'

    @admin.display(description='Location')
    def get_location(self, user):
        profile = getattr(user, 'profile', None)
        return profile.location.location_name if profile and profile.location else '-'


admin.site.unregister(User)
admin.site.register(User, UserWithProfileAdmin)
