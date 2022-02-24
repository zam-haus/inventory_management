from django.contrib import admin

# Register your models here.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserDirectory, UserConnection

from django.utils.translation import gettext_lazy as _


class UserConnectionInline(admin.StackedInline):
    model = UserConnection
    extra = 0
    can_add = False
    fields=('directory', 'directory_key', 'latest_directory_data',),
    readonly_fields = ('latest_directory_data',)


class UserAdmin(BaseUserAdmin):

    def user_directories(self, user):
        return list(UserDirectory.objects.filter(connected_users__user=user))

    inlines = [UserConnectionInline]
    fieldsets = (
        (None,
         {'fields':
              ('username', 'password', 'last_login', 'password_last_changed', 'date_joined')}),
        (_('Personal info'),
         {'fields':
              ('first_name', 'last_name', 'email')
          }),
        (_('Permissions'),
         {'fields':
              ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
          }),
    )
    list_display = (
    'username', 'email', 'first_name', 'last_name', 'is_staff', 'has_usable_password', 'user_directories')
    list_filter = (
        'is_staff', 'is_superuser', 'is_active', 'groups', 'password_last_changed', 'last_login', 'date_joined',
        'connections__directory__name')
    search_fields = ('username', 'display_name', 'first_name', 'last_name', 'email')
    readonly_fields = BaseUserAdmin.readonly_fields + ('username', 'password_last_changed', "last_login", "date_joined")


class UserConnectionAdmin(admin.ModelAdmin):
    fieldsets = (
        (None,
         {'fields':
              ('user', 'directory', 'directory_key', 'latest_directory_data')}),
    )
    list_display = ('user', 'directory', 'directory_key', 'latest_directory_data')
    list_filter = ('directory__name',)
    search_fields = ('user', 'directory', 'directory_key', 'latest_directory_data')
    readonly_fields = ()


class UserConnectionTabularInline(admin.TabularInline):
    model = UserConnection
    extra = 0
    fields = ('user','directory_key','latest_directory_data')
    readonly_fields = ()


class UserDirectoryAdmin(admin.ModelAdmin):
    fieldsets = (
        (None,
         {'fields':
              ('id', 'name', 'description')}),
    )
    list_display = ('name', 'description')
    list_filter = ()
    search_fields = ('id', 'name', 'description')
    readonly_fields = ('id',)
    inlines = [UserConnectionTabularInline]


admin.site.register(User, UserAdmin)
admin.site.register(UserDirectory, UserDirectoryAdmin)
#admin.site.register(UserDirectoryUsers, UserDirectoryUsersAdmin)
#admin.site.register(UserConnection, UserConnectionAdmin)
