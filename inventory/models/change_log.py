"""
The change log: one entry per change of an item, unique item, stock entry or location,
from the website, the admin or anywhere else, and per printed label (docs/change-log.md).
inventory/change_log.py writes the entries.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .stock import format_amount


class ChangeLog(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", _("Created")
        CHANGED = "changed", _("Changed")
        MOVED = "moved", _("Moved")
        DELETED = "deleted", _("Deleted")
        RESTORED = "restored", _("Restored")
        DISPOSED = "disposed", _("Removed from the inventory")
        STOCK = "stock", _("Stock changed")
        ATTACHED = "attached", _("Attachment added")
        DETACHED = "detached", _("Attachment removed")
        LABEL_ID = "label_id", _("Label ID")
        PRINTED = "printed", _("Label printed")

    class Source(models.TextChoices):
        DIALOG = "dialog", _("Stock dialog")
        WEB = "web", _("Website")
        ADMIN = "admin", _("Admin")
        DISSOLUTION = "dissolution", _("Location dissolution")
        PRINT = "print", _("Label printing")
        OTHER = "other", _("Other")

    class Direction(models.TextChoices):
        DECREASE = "decrease", _("Removal")
        INCREASE = "increase", _("Restock")

    class Reason(models.TextChoices):
        # Stock changes (REASONS) …
        SALE = "sale", _("Sale")
        OWN_USE = "own_use", _("ZAM's own use")
        RECOUNT_LOST = "recount_lost", _("Recount (lost or correction)")
        DESTRUCTION = "destruction", _("Destruction")
        OTHER = "other", _("Other")
        PURCHASE = "purchase", _("Purchase")
        DONATION = "donation", _("Donation")
        RECOUNT_FOUND = "recount_found", _("Recount (found or unknown origin)")
        # … and removals of unique items from the inventory (UniqueItem.DisposalReason).
        SOLD = "sold", _("Sold")
        SCRAPPED = "scrapped", _("Scrapped")
        LOST = "lost", _("Lost")
        RETURNED = "returned", _("Returned to owner")
        GIVEN_AWAY = "given_away", _("Given away")

    REASONS = {
        Direction.DECREASE: [Reason.SALE, Reason.OWN_USE, Reason.RECOUNT_LOST, Reason.DESTRUCTION, Reason.OTHER],
        Direction.INCREASE: [Reason.PURCHASE, Reason.DONATION, Reason.RECOUNT_FOUND],
    }

    created_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("user"),
    )
    actor_name = models.CharField(_("user name"), max_length=150, blank=True)
    source = models.CharField(_("source"), max_length=20, choices=Source.choices, default=Source.OTHER)
    action = models.CharField(_("action"), max_length=12, choices=Action.choices)
    # What changed, by model name and key; the label keeps entries readable after it is gone.
    subject_type = models.CharField(_("subject type"), max_length=32)
    subject_id = models.PositiveBigIntegerField(_("subject ID"), null=True, blank=True)
    subject_label = models.CharField(_("subject"), max_length=512, blank=True)
    # The pages that show the entry. other_location is where something was moved from, the parent of a new
    # location or the location of a removed stock entry's item.
    item = models.ForeignKey(
        "Item", null=True, blank=True, on_delete=models.SET_NULL, related_name="change_log", verbose_name=_("item"),
    )
    unique_item = models.ForeignKey(
        "UniqueItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="change_log",
        verbose_name=_("unique item"),
    )
    location = models.ForeignKey(
        "Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="change_log",
        verbose_name=_("location"),
    )
    other_location = models.ForeignKey(
        "Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name=_("other location"),
    )
    # [{"field": name, "before": value, "after": value, "internal": bool}]; values as shown, see change_log.value.
    changes = models.JSONField(_("changes"), default=list, blank=True)
    reason = models.CharField(_("reason"), max_length=20, choices=Reason.choices, blank=True)
    # Stock changes: direction, amounts before and after, changed amount, unit, unit price, estimate, removal.
    details = models.JSONField(_("details"), default=dict, blank=True)
    sale_value = models.DecimalField(_("sale value"), max_digits=18, decimal_places=2, null=True, blank=True)
    note = models.TextField(_("note"), blank=True)
    # Sent with each stock dialog change so that a retried submission is not applied twice.
    request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ("-created_at", "-pk")
        # The log is append-only: entries are never added by hand, changed or deleted.
        default_permissions = ("view",)
        permissions = [("view_changelog_actor", _("Can see who made a change in the change log"))]
        verbose_name = _("change log entry")
        verbose_name_plural = _("change log")
        indexes = [models.Index(fields=[field, "-created_at"], name=f"changelog_{field}_idx")
                   for field in ("item", "unique_item", "location", "other_location")]

    def __str__(self):
        return f"{self.get_action_display()}: {self.subject_label}"

    # Stock changes, from the details.
    def _amount(self, key):
        amount = self.details.get(key)
        return None if amount is None else Decimal(amount)

    @property
    def direction(self):
        return self.details.get("direction", "")

    @property
    def is_increase(self):
        return self.direction == self.Direction.INCREASE

    @property
    def amount(self):
        """The changed amount, always positive; None if unknown."""
        return self._amount("amount")

    @property
    def amount_before(self):
        return self._amount("before")

    @property
    def amount_after(self):
        """None once the stock entry was removed (entry_removed) or for a quick-item."""
        return self._amount("after")

    @property
    def is_estimate(self):
        return bool(self.details.get("estimated"))

    @property
    def entry_removed(self):
        return bool(self.details.get("removed"))

    def amount_text(self, amount):
        return format_amount(amount, self.details.get("unit", ""))
