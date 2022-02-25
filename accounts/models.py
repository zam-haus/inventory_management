import uuid

from django.db import models

from django.contrib.auth.models import AbstractUser

from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    password_last_changed = models.DateTimeField(
        _('password last changed'),
        default=timezone.now)
    directory_reference = models.TextField(
        null=True, blank=True, unique=True,
        help_text=_("This is the unique ID provided by the directory to identify this user"))
    latest_directory_data = models.JSONField(
        null=True, blank=True,
        help_text=_("This field contains the newest known data about this user. It might be outdated, though."))

    def set_password(self, raw_password):
        super().set_password(raw_password=raw_password)
        self.password_last_changed = timezone.now()

    def set_unusable_password(self):
        super(User, self).set_unusable_password()
        self.password_last_changed = timezone.now()

    def __str__(self):
        return f"User {repr(self.username)} ({self.get_full_name()})"
