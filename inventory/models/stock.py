"""Stock: how much of an item is where (changes are logged by inventory/change_log.py)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


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
        # Removing and adding stock in the stock dialog (granted to the local group by migration 0046).
        permissions = [("change_stock", _("Can remove and add stock in the stock dialog"))]

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

    def __str__(self):
        return f"{self.amount_text} @ {self.location.locatable_identifier}"
