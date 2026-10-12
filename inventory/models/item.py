"""Items and what describes them: categories, units, photos, files and barcodes.

An item is either a bulk item, counted per location in ItemLocation, or it is
tracked as unique items: single physical objects (unique_item.py). Never both."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from computedfields.models import ComputedFieldsModel, computed
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from sorl.thumbnail import delete

from ..ocr_util import ocr_on_image_path
from ..soft_delete import SoftDeleteModel


class UsageLevel(models.TextChoices):
    """Whether a briefing is needed before using something (German: Einweisungspflicht)."""

    GREEN = "green", _("green")
    YELLOW = "yellow", _("yellow")
    RED = "red", _("red")


USAGE_LEVEL_DESCRIPTIONS = {
    UsageLevel.GREEN: _("Green: free to use, no briefing required"),
    UsageLevel.YELLOW: _("Yellow: use with care, ask if in doubt"),
    UsageLevel.RED: _("Red: use only after a briefing"),
}
USAGE_LEVEL_SYMBOLS = {UsageLevel.GREEN: "✓", UsageLevel.YELLOW: "!", UsageLevel.RED: "✕"}


class Item(SoftDeleteModel):
    class Kind(models.TextChoices):
        BULK = "bulk", _("bulk item")
        UNIQUE = "unique", _("unique items")

    class Meta:
        verbose_name = _("item")
        verbose_name_plural = _("items")
        ordering = ["id"]
        permissions = [
            ("view_internal_details", _("Can view purchase prices and contact details of owners and responsible persons")),
        ]
        constraints = [
            # Only bulk items can be sold.
            models.CheckConstraint(
                name="item_only_bulk_for_sale",
                condition=models.Q(kind="bulk") | (
                    (models.Q(for_sale__isnull=True) | models.Q(for_sale=False)) & models.Q(sale_price__isnull=True)
                ),
            ),
            models.CheckConstraint(
                name="item_sale_price_only_for_sale",
                condition=models.Q(sale_price__isnull=True) | models.Q(for_sale=True),
            ),
        ]

    kind = models.CharField(_("kind"), max_length=8, choices=Kind.choices, default=Kind.BULK)
    name = models.CharField(_("item name"), max_length=512, blank=True, null=True)
    description = models.TextField(_("description"), blank=True)
    category = models.ForeignKey(
        "Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("category"),
    )
    measurement_unit = models.ForeignKey(
        "MeasurementUnit",
        on_delete=models.PROTECT,
        default=1,
        verbose_name=_("measurement unit"),
    )
    sale_price = models.DecimalField(
        _("sale price per unit"),
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        default=None,
    )
    # Unknown (None) until someone decides; many bulk items are for the ZAM's own use.
    for_sale = models.BooleanField(_("for sale"), null=True, blank=True, default=None)
    last_purchase_date = models.DateField(_("last purchase date"), null=True, blank=True)
    # Internal: shown only with inventory.view_internal_details.
    last_purchase_price = models.DecimalField(
        _("last purchase price"), max_digits=10, decimal_places=2, null=True, blank=True,
    )
    procurement_source = models.TextField(_("procurement source"), blank=True)
    usage_level = models.CharField(
        _("usage level"), max_length=8, choices=UsageLevel.choices, blank=True,
        help_text=_("Default for the unique items of this item; each one can override it."),
    )

    @property
    def general_images(self):
        """Photos of the item in general, not of one of its unique items (uses prefetched photos)."""
        return [image for image in self.itemimage_set.all() if image.unique_item_id is None]

    @property
    def unique_item_images(self):
        """Photos of its unique items still in the inventory (uses prefetched photos and unique items)."""
        return [image for image in self.itemimage_set.all()
                if image.unique_item_id is not None and image.unique_item.disposed_at is None]

    @property
    def tracks_unique_items(self):
        return self.kind == self.Kind.UNIQUE

    def clean(self):
        super().clean()
        errors = {}
        if self.tracks_unique_items and self.for_sale:
            errors["for_sale"] = _("Only bulk items can be for sale.")
        if self.tracks_unique_items and self.sale_price is not None:
            errors["sale_price"] = _("Only bulk items have a sale price.")
        elif self.sale_price is not None and self.for_sale is False:
            errors["sale_price"] = _("Items that are not for sale have no sale price.")
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list("kind", flat=True).first()
            if previous is not None and previous != self.kind and (
                self.itemlocation_set.exists() or self.unique_items.exists()
            ):
                errors["kind"] = _("The kind can only change while the item has no stock entries and no unique items.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # A price makes an undecided bulk item one for sale, wherever it is entered.
        if self.sale_price is not None and self.for_sale is None and not self.tracks_unique_items:
            self.for_sale = True
        super().save(*args, **kwargs)

    def __str__(self):
        if self.name:
            return self.name
        else:
            return _("Unnamed item") + f" {self.pk}"

    def get_absolute_url(self):
        return reverse("view_item", kwargs={"pk": self.pk})

    def get_admin_url(self):
        return reverse(
            "admin:inventory_item_change",
            args=(self.pk,),
        )


class Category(ComputedFieldsModel):
    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ("full_name",)

    name = models.CharField(_("category name"), max_length=512)
    description = models.TextField(_("description"), blank=True)
    parent_category = models.ForeignKey(
        "self",
        verbose_name=_("parent category"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    @computed(
        models.CharField(_("full name"), max_length=1024),
        depends=[("self", ["name"]), ("parent_category", ["full_name"])],
    )
    def full_name(self):
        if self.parent_category:
            return self.parent_category.full_name + "/" + self.name
        return self.name

    def __str__(self):
        return self.full_name


def get_item_upload_path(instance, filename):
    return f"items/{instance.item.id}/{datetime.now().isoformat()}_{filename}"


def get_document_upload_path(instance, filename):
    """
    Documents get an unguessable folder and are only served through a view that
    checks internal ones (DocumentView); the file keeps its name for downloads.
    """
    return f"documents/{uuid4().hex}/{Path(filename).name}"


def replaced_file_cleanup(instance, field_name, using, thumbnails=False):
    """
    When a saved photo or file gets a new upload, return the old file name and
    remove that file (and its thumbnails) once the change has been committed.
    """
    if not instance.pk:
        return None
    old = type(instance).objects.using(using).filter(pk=instance.pk).values_list(field_name, flat=True).first()
    new = getattr(instance, field_name)
    if not old or old == new.name:
        return None
    storage = new.storage

    def cleanup():
        if thumbnails:
            delete(old, delete_file=False)
        storage.delete(old)
    transaction.on_commit(cleanup, using=using)
    return old


class ItemLevelMixin(models.Model):
    """
    Photos and files belong to an item; set `unique_item` for those of one
    unique item only (e.g. its invoice), leave it empty for the item in general
    (e.g. a manual). The level can be changed later.
    """

    class Meta:
        abstract = True

    @property
    def is_general(self):
        return self.unique_item_id is None

    def clean(self):
        super().clean()
        if self.unique_item_id and self.item_id and self.unique_item.item_id != self.item_id:
            raise ValidationError({"unique_item": _("This unique item belongs to another item.")})

    def save(self, *args, **kwargs):
        if self.unique_item_id:
            self.item_id = self.unique_item.item_id
        super().save(*args, **kwargs)


class ItemImage(ItemLevelMixin, models.Model):
    class Meta:
        verbose_name = _("photo")
        verbose_name_plural = _("photos")
        # The primary photo comes first wherever photos are shown.
        ordering = ["-is_primary", "pk"]
        constraints = [
            # One primary photo for the item in general and one per unique item.
            models.UniqueConstraint(fields=["item"], condition=models.Q(is_primary=True, unique_item__isnull=True),
                                    name="itemimage_one_general_primary"),
            models.UniqueConstraint(fields=["unique_item"], condition=models.Q(is_primary=True),
                                    name="itemimage_one_primary_per_unique_item"),
        ]

    image = models.ImageField(_("image"), upload_to=get_item_upload_path)
    description = models.CharField(_("description"), max_length=512, blank=True)
    is_primary = models.BooleanField(_("primary photo"), default=False)
    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("item"))
    unique_item = models.ForeignKey(
        "UniqueItem", on_delete=models.CASCADE, null=True, blank=True, related_name="images",
        verbose_name=_("belongs to"),
    )
    ocr_text = models.TextField(_("ocr text"), blank=True, null=True, editable=False)
    ocr_timestamp = models.DateTimeField(_("text recognized on"), blank=True, null=True)

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        if replaced_file_cleanup(self, "image", using, thumbnails=True):
            # An edited photo needs new text recognition.
            self.ocr_text = self.ocr_timestamp = None
        super().save(*args, **kwargs)

    def image_tag(self, location=None):
        return format_html('<img src="{}" width="512" />', self.image.url)
    image_tag.short_description = "Image"

    def update_ocr_text(self, ocr_text):
        self.ocr_text = ocr_text
        self.ocr_timestamp = timezone.now()
        self.save()

    def run_ocr(self):
        ocr_text = ocr_on_image_path(self.image.path)
        self.update_ocr_text(ocr_text)
        return ocr_text


@receiver(pre_delete, sender=ItemImage)
def delete_image(sender, instance, using, **kwargs):
    image = instance.image
    if image:
        def cleanup():
            delete(image, delete_file=False)
            image.delete(save=False)
        transaction.on_commit(cleanup, using=using)


class Document(models.Model):
    """A file attached to an item or unique item. Internal documents need inventory.view_internal_details."""

    file = models.FileField(_("file"), upload_to=get_document_upload_path, max_length=255)
    description = models.CharField(_("description"), max_length=512, blank=True)
    internal = models.BooleanField(
        _("internal document"), default=False,
        help_text=_("Only people allowed to see internal details can open it; others only see its name."),
    )

    class Meta:
        abstract = True
        ordering = ["internal", "pk"]

    @property
    def display_name(self):
        return self.description or Path(self.file.name).name


class ItemFile(ItemLevelMixin, Document):
    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("item"))
    unique_item = models.ForeignKey(
        "UniqueItem", on_delete=models.CASCADE, null=True, blank=True, related_name="files",
        verbose_name=_("belongs to"),
    )

    class Meta(Document.Meta):
        verbose_name = _("file")
        verbose_name_plural = _("files")

    def get_absolute_url(self):
        return reverse("item_file", kwargs={"pk": self.pk})

    def save(self, *args, **kwargs):
        replaced_file_cleanup(self, "file", kwargs.get("using") or router.db_for_write(type(self), instance=self))
        super().save(*args, **kwargs)


@receiver(pre_delete, sender=ItemFile)
def delete_file(sender, instance, using, **kwargs):
    file = instance.file
    if file:
        transaction.on_commit(lambda: file.delete(save=False), using=using)


class ItemBarcode(models.Model):
    class Meta:
        verbose_name = _("barcode")
        verbose_name_plural = _("barcodes")

    data = models.TextField(_("data"))
    type = models.ForeignKey(
        "BarcodeType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("type"),
    )
    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("Item"))

    def __str__(self):
        return f"{repr(self.data)} ({self.type})"


class BarcodeType(models.Model):
    class Meta:
        verbose_name = _("barcode type")
        verbose_name_plural = _("barcode types")

    name = models.CharField(_("name"), max_length=128, unique=True)

    def __str__(self):
        return self.name


class MeasurementUnit(models.Model):
    class Meta:
        verbose_name = _("measurement unit")
        verbose_name_plural = _("measurement units")

    name = models.CharField(_("name"), max_length=128, unique=True)
    short = models.CharField(_("abbreviation"), max_length=8, unique=True)
    description = models.TextField(_("description"), blank=True)

    def __str__(self):
        return f"{self.name} ({self.short})"
