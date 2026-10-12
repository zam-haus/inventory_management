"""Stock: how much of an item is where, and the log of every change."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..stock_log import current_stock_changes
from .item import Item
from .location import Location


# Stored amounts: positive numbers are precise, negative ones rough estimates,
# with -1 meaning "few" and -9999 "many". NULL is unknown (a quick-item).
FEW, MANY = Decimal(-1), Decimal(-9999)


def amount_kind(amount):
    if amount is None:
        return "unknown"
    if amount == FEW:
        return "few"
    if amount == MANY:
        return "many"
    return "estimate" if amount < 0 else "precise"


def amount_without_zeros(amount):
    if amount is None:
        return None
    for i in range(4):
        rounded_amount = round(amount, i)
        if rounded_amount == amount:
            return rounded_amount


def format_amount(amount, unit):
    if amount is None:
        return _("amount unknown")
    if amount < 0:
        if amount == FEW:
            unspecific_amount_string = _("few")
        elif amount == MANY:
            unspecific_amount_string = _("many")
        else:
            unspecific_amount_string = f"~{-amount_without_zeros(amount)}"
        return f"{unspecific_amount_string} {unit}"
    return f"{amount_without_zeros(amount)} {unit}"


def stock_change(before, after):
    """Return (direction, changed amount or None if unknown, estimated) or None if unchanged.

    `after` is None when the stock entry itself is removed. Quick-items (unknown
    amount) are not stock yet: removing them or giving them an amount is no
    change. "Few" and "many" are compared as 1 and 9999.
    """
    if before is None:
        return None
    removed_entry = after is None
    after = Decimal(0) if removed_entry else after
    if abs(after) == abs(before) and not removed_entry:
        return None
    direction = "increase" if abs(after) > abs(before) else "decrease"
    estimated = before < 0 or after < 0
    if before in (FEW, MANY) or after in (FEW, MANY):
        return direction, None, estimated
    return direction, abs(abs(after) - abs(before)), estimated


class ItemLocation(models.Model):
    class Meta:
        verbose_name = _("stock entry")
        verbose_name_plural = _("stock entries")
        unique_together = ["item", "location"]
        order_with_respect_to = "location"

    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("item"))
    location = models.ForeignKey(
        "Location", on_delete=models.CASCADE, verbose_name=_("location")
    )
    # An unknown amount (NULL) marks a quick-item, created by title only on the
    # location page; entering an amount turns it into a regular item.
    amount = models.DecimalField(
        max_digits=16, decimal_places=3, verbose_name=_("amount"), null=True, blank=True,
        help_text=_("positive numbers are precise, negative numbers are rough estimates. "
                    "-1 is 'few' and -9999 is 'many'. Empty means unknown.")
    )

    @property
    def is_quick_item(self):
        return self.amount is None

    def clean(self):
        super().clean()
        if self.item_id and self.item.tracks_unique_items:
            raise ValidationError({"item": _("This item is tracked as unique items; add unique items instead of stock.")})

    @property
    def sale_value(self):
        if self.item.sale_price is None or self.amount is None or self.amount in (-1, -9999):
            return None
        return abs(self.amount) * self.item.sale_price

    @property
    def amount_kind(self):
        return amount_kind(self.amount)

    @property
    def amount_without_zeros(self):
        return amount_without_zeros(self.amount)

    @property
    def amount_text(self):
        return format_amount(self.amount, self.item.measurement_unit.short)

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = None
            if self.pk:
                previous = type(self).objects.using(using).select_for_update().filter(
                    pk=self.pk).values("amount", "location_id").first()
            result = super().save(*args, **kwargs)
            context = current_stock_changes()
            if previous is not None and (context is None or context["log"]):
                after = type(self).objects.using(using).values_list("amount", flat=True).get(pk=self.pk)
                change = stock_change(previous["amount"], after)
                if change is not None:
                    direction, amount, estimated = change
                    # A change combined with a move is logged where the stock was.
                    StockChange.record(
                        self, direction=direction, location=Location.objects.using(using).get(pk=previous["location_id"]),
                        amount_before=previous["amount"], amount_after=after,
                        amount=amount, is_estimate=estimated, using=using,
                    )
            return result

    def __str__(self):
        return f"{self.amount_text} @ {self.location.locatable_identifier}"


class StockChange(models.Model):
    """One increase or decrease of stock at a location. Only staff can see it, in the admin."""

    class Direction(models.TextChoices):
        DECREASE = "decrease", _("Removal")
        INCREASE = "increase", _("Restock")

    class Reason(models.TextChoices):
        SALE = "sale", _("Sale")
        OWN_USE = "own_use", _("ZAM's own use")
        RECOUNT_LOST = "recount_lost", _("Recount (lost or correction)")
        DESTRUCTION = "destruction", _("Destruction")
        OTHER = "other", _("Other")
        PURCHASE = "purchase", _("Purchase")
        DONATION = "donation", _("Donation")
        RECOUNT_FOUND = "recount_found", _("Recount (found or unknown origin)")

    REASONS = {
        Direction.DECREASE: [Reason.SALE, Reason.OWN_USE, Reason.RECOUNT_LOST, Reason.DESTRUCTION, Reason.OTHER],
        Direction.INCREASE: [Reason.PURCHASE, Reason.DONATION, Reason.RECOUNT_FOUND],
    }

    class Source(models.TextChoices):
        DIALOG = "dialog", _("Stock dialog")
        ITEM_FORM = "item_form", _("Item form")
        ADMIN = "admin", _("Admin")
        DISSOLUTION = "dissolution", _("Location dissolution")
        OTHER = "other", _("Other")

    created_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("user"),
    )
    direction = models.CharField(_("direction"), max_length=10, choices=Direction.choices)
    reason = models.CharField(_("reason"), max_length=20, choices=Reason.choices)
    note = models.TextField(_("note"), blank=True)
    source = models.CharField(_("source"), max_length=20, choices=Source.choices, default=Source.OTHER)
    # Names are kept so entries stay readable after the item or location is gone.
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("item"))
    item_name = models.CharField(_("item name"), max_length=512)
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("location"),
    )
    location_name = models.CharField(_("location name"), max_length=512)
    amount_before = models.DecimalField(_("amount before"), max_digits=16, decimal_places=3, null=True, blank=True)
    amount_after = models.DecimalField(_("amount after"), max_digits=16, decimal_places=3, null=True, blank=True)
    entry_removed = models.BooleanField(_("removed from location"), default=False)
    amount = models.DecimalField(
        _("changed amount"), max_digits=16, decimal_places=3, null=True, blank=True,
        help_text=_("Always positive; empty if unknown."),
    )
    is_estimate = models.BooleanField(_("estimated"), default=False)
    unit = models.CharField(_("measurement unit"), max_length=8)
    unit_price = models.DecimalField(
        _("sale price per unit"), max_digits=8, decimal_places=2, null=True, blank=True,
    )
    sale_value = models.DecimalField(_("sale value"), max_digits=18, decimal_places=2, null=True, blank=True)
    # Sent with each change so that a retried submission is not applied twice.
    request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ("-created_at", "-pk")
        # The log is append-only: entries are never changed or deleted.
        default_permissions = ("add", "view")
        verbose_name = _("stock change")
        verbose_name_plural = _("stock changes")

    @classmethod
    def record(cls, entry, *, direction, amount, is_estimate, amount_before, amount_after=None,
               entry_removed=False, location=None, item=None, actor=None, reason=None, note="",
               source=None, link_item=True, link_location=True, request_id=None, using=None):
        """Log a change of `entry`; unset attribution comes from `stock_changes()`."""
        context = current_stock_changes() or {}
        actor = actor if actor is not None else context.get("actor")
        if reason is None:
            default = cls.Reason.RECOUNT_FOUND if direction == cls.Direction.INCREASE else cls.Reason.OTHER
            reason = context.get(f"{direction}_reason") or default
        item = item if item is not None else entry.item
        location = location if location is not None else entry.location
        price = item.sale_price
        sale_value = None
        if amount is not None and price is not None:
            sale_value = (amount * price).quantize(Decimal("0.01"))
        return cls.objects.using(using).create(
            actor=actor, direction=direction, reason=reason, note=note or context.get("note", ""),
            source=source or context.get("source") or cls.Source.OTHER,
            item=item if link_item else None, item_name=str(item),
            location=location if link_location else None, location_name=str(location),
            amount_before=amount_before, amount_after=None if entry_removed else amount_after,
            entry_removed=entry_removed, amount=amount, is_estimate=is_estimate,
            unit=item.measurement_unit.short, unit_price=price, sale_value=sale_value, request_id=request_id,
        )

    @property
    def is_increase(self):
        return self.direction == self.Direction.INCREASE

    def amount_text(self, amount):
        return format_amount(amount, self.unit)

    def __str__(self):
        return f"{self.item_name} @ {self.location_name}"


def _deletes(origin, model):
    if isinstance(origin, model):
        return True
    return isinstance(origin, models.QuerySet) and origin.model is model


@receiver(pre_delete, sender=ItemLocation)
def log_stock_entry_removal(sender, instance, using, origin=None, **kwargs):
    context = current_stock_changes()
    if context is not None and not context["log"]:
        return
    before = ItemLocation.objects.using(using).filter(pk=instance.pk).values_list("amount", flat=True).first()
    change = stock_change(before, None)
    if change is None:
        return
    direction, amount, estimated = change
    # Records deleted along with the entry are referenced by name only.
    StockChange.record(
        instance, direction=direction,
        item=Item.objects.using(using).select_related("measurement_unit").get(pk=instance.item_id),
        location=Location.objects.using(using).get(pk=instance.location_id),
        link_item=not _deletes(origin, Item), link_location=not _deletes(origin, Location),
        amount_before=before, entry_removed=True, amount=amount, is_estimate=estimated, using=using,
    )
