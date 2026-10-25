"""
Unique items: single physical objects of an item tracked as unique items (an
Item with kind "unique"), such as one particular fire extinguisher. Each one is
at exactly one location and identified by its label ID. Unique items are never
deleted: they leave the inventory by being disposed; the change log keeps their
history.
"""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..actor import acting_as
from .item import UsageLevel


class ActiveUniqueItemManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(disposed_at__isnull=True)


class UniqueItem(models.Model):
    class DisposalReason(models.TextChoices):
        SOLD = "sold", _("Sold")
        SCRAPPED = "scrapped", _("Scrapped")
        LOST = "lost", _("Lost")
        RETURNED = "returned", _("Returned to owner")
        GIVEN_AWAY = "given_away", _("Given away")
        OTHER = "other", _("Other")

    item = models.ForeignKey(
        "Item", on_delete=models.PROTECT, related_name="unique_items", verbose_name=_("item"),
        limit_choices_to={"kind": "unique"},
    )
    # Optional, to tell unique items of one item apart; shown between the item and the label ID (__str__).
    name = models.CharField(
        _("name"), max_length=100, blank=True,
        help_text=_("Optional, to tell it apart from others of the item, e.g. “blue” or “spare for the workshop”. "
                    "It is shown between the item's name and its label ID."),
    )
    # Empty only once the unique item has been disposed (see the constraint below).
    location = models.ForeignKey(
        "Location", on_delete=models.PROTECT, null=True, blank=True, related_name="unique_items",
        verbose_name=_("location"),
    )
    notes = models.TextField(_("notes"), blank=True, help_text=_("Markdown is supported."))
    warranty_until = models.DateField(_("warranty until"), null=True, blank=True)
    purchase_date = models.DateField(_("purchase date"), null=True, blank=True)
    # Internal: shown only with inventory.view_internal_details.
    purchase_price = models.DecimalField(_("purchase price"), max_digits=10, decimal_places=2, null=True, blank=True)
    procurement_source = models.TextField(_("procurement source"), blank=True)
    usage_level = models.CharField(
        _("usage level"), max_length=8, choices=UsageLevel.choices, blank=True,
        help_text=_("Leave empty to use the level of the item."),
    )
    responsible_team = models.ForeignKey(
        "accounts.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("responsible team"),
    )
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("responsible person"),
    )
    # Without an owner the unique item belongs to the ZAM. First names are public;
    # full names and contact details are internal.
    # PROTECT: deleting the account must not silently turn the unique item into ZAM property.
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name=_("owner (account)"),
    )
    owner_first_name = models.CharField(
        _("owner's first name"), max_length=150, blank=True,
        help_text=_("For owners without an account. Shown publicly."),
    )
    owner_contact = models.TextField(
        _("owner's name and contact"), blank=True,
        help_text=_("For owners without an account. Internal."),
    )
    disposed_at = models.DateTimeField(_("disposed at"), null=True, blank=True)
    disposal_reason = models.CharField(_("disposal reason"), max_length=12, choices=DisposalReason.choices, blank=True)
    disposal_note = models.TextField(_("disposal note"), blank=True)

    objects = models.Manager()
    active = ActiveUniqueItemManager()

    class Meta:
        verbose_name = _("unique item")
        verbose_name_plural = _("unique items")
        ordering = ["item__name", "pk"]
        permissions = [
            ("dispose_uniqueitem", _("Can remove a unique item from the inventory")),
            # The owner is set when the unique item is created; changing it later is restricted.
            ("change_uniqueitem_owner", _("Can change the owner of a unique item after it was created")),
        ]
        constraints = [
            models.CheckConstraint(
                name="unique_item_located_unless_disposed",
                condition=models.Q(disposed_at__isnull=False) | models.Q(location__isnull=False),
            ),
        ]

    def __str__(self):
        """The item, its own name if it has one, and its label ID: "Akkuschrauber blau K7R-4XD"."""
        return " ".join(part for part in (str(self.item), self.name, self.label_display or f"#{self.pk}") if part)

    def get_absolute_url(self):
        return reverse("view_unique_item", kwargs={"pk": self.pk})

    @property
    def label_code(self):
        """The active label ID code; annotate_label_code() fills it without a query."""
        if "_label_code" not in self.__dict__:
            from ..label_ids.lookup import active_code
            self._label_code = active_code(self)
        return self._label_code

    @label_code.setter
    def label_code(self, value):
        self._label_code = value

    @property
    def label_display(self):
        from ..label_ids import core
        return core.display(self.label_code) if self.label_code else ""

    @property
    def is_disposed(self):
        return self.disposed_at is not None

    @property
    def effective_usage_level(self):
        return self.usage_level or self.item.usage_level

    def get_effective_usage_level_display(self):
        level = self.effective_usage_level
        return UsageLevel(level).label if level else ""

    @property
    def warranty_expired(self):
        return self.warranty_until is not None and self.warranty_until < timezone.localdate()

    @property
    def has_owner(self):
        return bool(self.owner_user_id or self.owner_first_name or self.owner_contact)

    @property
    def owner_first_name_display(self):
        return self.owner_user.first_name if self.owner_user_id else self.owner_first_name

    @property
    def responsible_first_name(self):
        return self.responsible_user.first_name if self.responsible_user_id else ""

    def clean(self):
        super().clean()
        errors = {}
        if self.item_id and not self.item.tracks_unique_items:
            errors["item"] = _("Bulk items cannot have unique items.")
        if self.disposed_at is None:
            if self.location_id is None:
                errors["location"] = _("A unique item in the inventory needs a location.")
            elif self.location.is_deleted:
                errors["location"] = _("Deleted locations cannot be used as destinations.")
        if self.owner_user_id and (self.owner_first_name or self.owner_contact):
            errors["owner_user"] = _("Choose an owner account or enter the owner's details, not both.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, actor=None, **kwargs):
        """Saves; the change log records it with `actor` or the current user as who acted."""
        with acting_as(actor):
            super().save(*args, **kwargs)

    def dispose(self, reason, note="", actor=None):
        """Remove the unique item from the inventory. Its label ID stays assigned."""
        self.disposed_at = timezone.now()
        self.disposal_reason = reason
        self.disposal_note = note
        self.location = None
        self.save(actor=actor)


def get_unique_item_upload_path(instance, filename):
    # Only referenced by migrations: unique item photos and files are now ItemImage and ItemFile rows.
    return f"unique_items/{instance.unique_item.id}/{uuid4().hex}{Path(filename).suffix.lower()}"
