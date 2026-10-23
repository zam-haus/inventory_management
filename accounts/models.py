import uuid

from django.contrib.auth.models import AbstractUser, Group
from django.core.validators import RegexValidator
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
    # Marks the team's locations (docs/location-structure.md); never resolved as an ID.
    code = models.CharField(
        _("code"), max_length=4, blank=True,
        validators=[RegexValidator(r"^\S*$", message=_("No spaces allowed."))],
        help_text=_("Short code shown as a badge, e.g. H for the wood workshop or ⌂ for the caretakers."),
    )
    color = models.CharField(
        _("colour"), max_length=7, blank=True,
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", message=_("Enter a colour like #7d3a2d."))],
        help_text=_("Badge colour as #rrggbb. Without one, the badge uses the parent team's colour."),
    )
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subteams",
        verbose_name=_("parent team"),
    )

    class Meta:
        verbose_name = _("team")
        verbose_name_plural = _("teams")
        ordering = ["group__name"]
        constraints = [
            models.UniqueConstraint(fields=["code"], condition=~models.Q(code=""), name="team_code_unique"),
        ]

    def __str__(self):
        return self.group.name

    @property
    def badge_color(self):
        """The team's colour, else the nearest parent team's, else ""."""
        team, seen = self, set()
        while team is not None and team.pk not in seen:
            if team.color:
                return team.color
            seen.add(team.pk)
            team = team.parent
        return ""

    @property
    def badge_text_color(self):
        """Black or white, whichever contrasts more with the badge colour (WCAG relative luminance)."""
        color = self.badge_color
        if not color:
            return ""
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#000000" if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else "#ffffff"
