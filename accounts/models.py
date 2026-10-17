import uuid

from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    password_last_changed = models.DateTimeField(
        _('password last changed'),
        default=timezone.now)
    directory_reference = models.TextField(
        _("directory reference"), null=True, blank=True, unique=True,
        help_text=_("This is the unique ID provided by the directory to identify this user"))
    latest_directory_data = models.JSONField(
        _("latest directory data"), null=True, blank=True,
        help_text=_("This field contains the newest known data about this user. It might be outdated, though."))

    @property
    def is_local_member(self):
        from .groups import local_group_name

        return self.groups.filter(name=local_group_name()).exists()

    def set_password(self, raw_password):
        super().set_password(raw_password=raw_password)
        self.password_last_changed = timezone.now()

    def set_unusable_password(self):
        super().set_unusable_password()
        self.password_last_changed = timezone.now()

    def __str__(self):
        return f"User {repr(self.username)} ({self.get_full_name()})"


class Team(models.Model):
    """
    A group that can be named as responsible for things. Membership comes from
    the directory but is only ever added (accounts/auth.py), so a team is a
    public label, never a basis for permissions or notifications.
    """
    group = models.OneToOneField(Group, on_delete=models.CASCADE, verbose_name=_("group"))
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("team")
        verbose_name_plural = _("teams")
        ordering = ["group__name"]

    def __str__(self):
        return self.group.name
