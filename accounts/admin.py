from django.contrib import admin

# Register your models here.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User

from django.utils.translation import gettext_lazy as _


class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None,
         {'fields':
              ('username', 'password', 'last_login', 'password_last_changed', 'date_joined')}),
        (_('Personal info'),
         {'fields':
              ('first_name', 'last_name', 'email', 'directory_reference', 'latest_directory_data')
          }),
        (_('Permissions'),
         {'fields':
              ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
          }),
    )
    list_display = (
        'username', 'email', 'first_name', 'last_name', 'is_staff', 'has_usable_password')
    list_filter = (
        'is_staff', 'is_superuser', 'is_active', 'groups', 'password_last_changed', 'last_login', 'date_joined',)
    search_fields = ('username', 'display_name', 'first_name', 'last_name', 'email')
    readonly_fields = BaseUserAdmin.readonly_fields + ('username', 'password_last_changed', "last_login", "date_joined", "latest_directory_data")

admin.site.register(User, UserAdmin)
