"""
Unique items: single physical objects of an item tracked as unique items (an
Item with kind "unique"), such as one particular fire extinguisher. Each one is
at exactly one location and identified by its label ID. Unique items are never
deleted: they leave the inventory by being disposed, and UniqueItemEvent keeps
their history.
"""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..actor import current_actor
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
        code = self.label_display
        return f"{self.item} {code}" if code else f"{self.item} #{self.pk}"

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

    OWNER_FIELDS = ("owner_user_id", "owner_first_name", "owner_contact")

    def owner_snapshot(self, side):
        """The current owner as event fields for the given side ("from" or "to")."""
        return {
            f"{side}_owner_user_id": self.owner_user_id,
            f"{side}_owner_name": self.owner_first_name_display or "",
            f"{side}_owner_contact": self.owner_contact,
        }

    def save(self, *args, actor=None, **kwargs):
        """Saves and records creation, moves, owner changes and disposal in the unique item's history."""
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        actor = actor or current_actor()
        with transaction.atomic(using=using):
            previous = None
            if self.pk:
                previous = type(self).objects.using(using).select_for_update().filter(pk=self.pk).first()
            result = super().save(*args, **kwargs)
            events = UniqueItemEvent.objects.using(using)
            event = {"unique_item": self, "actor": actor}
            if previous is None:
                owner = self.owner_snapshot("to") if self.has_owner else {}
                events.create(**event, type=UniqueItemEvent.Type.CREATED, to_location=self.location, **owner)
                return result
            if any(getattr(previous, field) != getattr(self, field) for field in self.OWNER_FIELDS):
                events.create(
                    **event, type=UniqueItemEvent.Type.OWNER_CHANGED,
                    **previous.owner_snapshot("from"), **self.owner_snapshot("to"),
                )
            if previous.disposed_at is None and self.disposed_at is not None:
                events.create(
                    **event, type=UniqueItemEvent.Type.DISPOSED, from_location_id=previous.location_id,
                    reason=self.disposal_reason, note=self.disposal_note,
                )
            elif previous.location_id != self.location_id:
                events.create(
                    **event, type=UniqueItemEvent.Type.MOVED, from_location_id=previous.location_id,
                    to_location=self.location,
                )
            return result

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


class UniqueItemEvent(models.Model):
    """One entry in a unique item's history. The log is append-only; only staff see who acted, in the admin."""

    class Type(models.TextChoices):
        CREATED = "created", _("Added to the inventory")
        MOVED = "moved", _("Moved")
        DISPOSED = "disposed", _("Removed from the inventory")
        OWNER_CHANGED = "owner", _("Owner changed")

    created_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("user"),
    )
    type = models.CharField(_("event"), max_length=12, choices=Type.choices)
    unique_item = models.ForeignKey(UniqueItem, on_delete=models.PROTECT, related_name="events", verbose_name=_("unique item"))
    # Names are kept so entries stay readable after a location is gone.
    from_location = models.ForeignKey(
        "Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("from"),
    )
    from_location_name = models.CharField(_("from"), max_length=512, blank=True)
    to_location = models.ForeignKey(
        "Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=_("to"),
    )
    to_location_name = models.CharField(_("to"), max_length=512, blank=True)
    # Owner before and after: first names are public, account and contact are internal.
    # No owner on both sides means the ZAM.
    from_owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("previous owner (account)"),
    )
    from_owner_name = models.CharField(_("previous owner's first name"), max_length=150, blank=True)
    from_owner_contact = models.TextField(_("previous owner's name and contact"), blank=True)
    to_owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("new owner (account)"),
    )
    to_owner_name = models.CharField(_("new owner's first name"), max_length=150, blank=True)
    to_owner_contact = models.TextField(_("new owner's name and contact"), blank=True)
    reason = models.CharField(_("reason"), max_length=12, choices=UniqueItem.DisposalReason.choices, blank=True)
    note = models.TextField(_("note"), blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        default_permissions = ("add", "view")
        verbose_name = _("unique item event")
        verbose_name_plural = _("unique item events")

    def save(self, *args, **kwargs):
        if self.from_location_id and not self.from_location_name:
            self.from_location_name = str(self.from_location)
        if self.to_location_id and not self.to_location_name:
            self.to_location_name = str(self.to_location)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_type_display()}: {self.unique_item}"

    def _owner_label(self, side):
        name = getattr(self, f"{side}_owner_name")
        if name:
            return name
        if getattr(self, f"{side}_owner_user_id") or getattr(self, f"{side}_owner_contact"):
            return _("someone else")  # an owner without a public first name
        return _("ZAM")

    @property
    def from_owner_label(self):
        return self._owner_label("from")

    @property
    def to_owner_label(self):
        return self._owner_label("to")

    @property
    def owner_details(self):
        """Internal: (account, contact, label) of the owner before and after."""
        if self.type != self.Type.OWNER_CHANGED:
            return [(self.to_owner_user, self.to_owner_contact, "")]
        return [(self.from_owner_user, self.from_owner_contact, _("before")),
                (self.to_owner_user, self.to_owner_contact, _("after"))]

    @property
    def has_to_owner(self):
        return bool(self.to_owner_name or self.to_owner_user_id or self.to_owner_contact)
