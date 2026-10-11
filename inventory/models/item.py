"""Items and what describes them: categories, units, photos, files and barcodes."""
from datetime import datetime

from computedfields.models import ComputedFieldsModel, computed
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from sorl.thumbnail import delete

from ..ocr_util import ocr_on_image_path
from ..soft_delete import SoftDeleteModel


class Item(SoftDeleteModel):
    class Meta:
        verbose_name = _("item")
        verbose_name_plural = _("items")
        ordering = ["id"]

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

    def __str__(self):
        if self.name:
            return self.name
        else:
            return _("Unnamed item") + f" {self.pk}"

    def get_absolute_url(self):
        return reverse("view_item", kwargs={"pk": self.pk})

    def validate_deletion(self, *, hard=False, soft_ids=(), hard_ids=()):
        # A printed ZAM ID label keeps pointing here; see models/zamid.py.
        if hard and self.zam_ids.exists():
            raise ValidationError(_("The item has a ZAM ID label and cannot be deleted permanently."))

    def get_admin_url(self):
        return reverse(
            "admin:inventory_item_change",
            args=(self.pk,),
        )

    @classmethod
    def filter_incomplete(cls, ordered=False):
        # prefilter:
        # only with image(s)
        relevant_items = cls.active.filter(itemimage__isnull=False, itemlocation__location__is_deleted=False)

        # filter with complete information
        relevant_items = relevant_items.exclude(name__isnull=False, sale_price__isnull=False)

        if ordered:
            # prioritize items with price label image
            relevant_items = relevant_items.annotate(
                pl_count=models.Count('itemimage', filter=models.Q(itemimage__description="Price label")))

            # sorted by price label count and amount:
            relevant_items = relevant_items.annotate(
                amount=models.Sum(models.functions.math.Abs('itemlocation__amount')))
            relevant_items = relevant_items.order_by('-pl_count', '-amount')

        return relevant_items


class Category(ComputedFieldsModel):
    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ("full_name",)

    name = models.CharField(_("category name"), max_length=512)
    description = models.TextField(blank=True)
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


class ItemImage(models.Model):
    image = models.ImageField(_("image"), upload_to=get_item_upload_path)
    description = models.CharField(_("description"), max_length=512, blank=True)
    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("item"))
    ocr_text = models.TextField(_("ocr text"), blank=True, null=True, editable=False)
    ocr_timestamp = models.DateTimeField(blank=True, null=True)

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


class ItemFile(models.Model):
    file = models.FileField(_("file"), upload_to=get_item_upload_path)
    description = models.CharField(_("description"), max_length=512, blank=True)
    item = models.ForeignKey("Item", on_delete=models.CASCADE, verbose_name=_("file"))


@receiver(pre_delete, sender=ItemFile)
def delete_file(sender, instance, using, **kwargs):
    file = instance.file
    if file:
        transaction.on_commit(lambda: file.delete(save=False), using=using)


class ItemBarcode(models.Model):
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
