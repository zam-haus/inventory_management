import uuid

from django.db import models

from django.contrib.auth.models import AbstractUser

from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    password_last_changed = models.DateTimeField(_('password last changed'), default=timezone.now)

    def set_password(self, raw_password):
        super().set_password(raw_password=raw_password)
        self.password_last_changed = timezone.now()

    def set_unusable_password(self):
        super(User, self).set_unusable_password()
        self.password_last_changed = timezone.now()

    def __str__(self):
        return f"User {repr(self.username)} ({self.get_full_name()})"


class UserDirectory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    description = models.TextField(null=False,blank=True,default=str)
    name = models.TextField(null=False, unique=True, default=str)

    def __str__(self):
        return f"Directory {repr(self.name)}"

    pass


class UserConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="connections",
                             help_text="This refers to a user who can be logged in using a directory")
    directory = models.ForeignKey(UserDirectory, on_delete=models.CASCADE, related_name="connected_users",
                                  help_text="This refers to the directory used to log in the user")
    directory_key = models.TextField(null=False,
                                     help_text="This is the unique ID provided by the directory to identify this user")
    latest_directory_data = models.JSONField(null=True, blank=True,
                                             help_text="This field contains the newest known data about this user. It might be outdated, though.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['directory', 'directory_key'],name="unique_directory_key"),
        ]

    def __str__(self):
        return f"Link {self.user.username} <-> {self.directory})"
