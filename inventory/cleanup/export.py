"""The cleanup export: the category tree and every item's texts, with the format for proposals (format.md)."""
from pathlib import Path

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from ..models import Category, Item, ItemBarcode, ItemFile, ItemImage
from ..public_export import export_filter, publishable

KIND = "zam-inventory-cleanup-export"
VERSION = 1
FORMAT = Path(__file__).with_name("format.md")

# What the export holds, by model and field. Only what the public data export keeps (public_export.py), like
# the search: the file is meant for processing outside.
FIELDS = {
    "inventory.category": ("name", "description", "keywords", "naming"),
    "inventory.item": ("name", "description"),
    "inventory.itembarcode": ("data",),
    "inventory.itemimage": ("description", "ocr_text"),
    "inventory.itemfile": ("description",),
}


def check_fields():
    """The fields of FIELDS the public export does not keep (to be removed from FIELDS)."""
    return [f"{label}.{name}" for label, names in FIELDS.items() for name in names if not publishable(label, name)]


def rows(model):
    return model.objects.filter(**export_filter(model._meta.label_lower))


def text(value):
    return (value or "").strip()


def build():
    """The export as a dict (written as JSON)."""
    problems = check_fields()
    if problems:
        raise ValueError(f"Not in the public export: {', '.join(problems)}")
    categories = rows(Category).annotate(
        item_count=Count("item", filter=Q(item__is_deleted=False))).order_by("full_name")
    items = Item.active.filter(**export_filter("inventory.item")).select_related("category").prefetch_related(
        Prefetch("itembarcode_set", queryset=rows(ItemBarcode).select_related("type").order_by("pk")),
        Prefetch("itemimage_set", queryset=rows(ItemImage).order_by("pk")),
        Prefetch("itemfile_set", queryset=rows(ItemFile).order_by("pk")),
    ).order_by("pk")
    return {
        "kind": KIND,
        "version": VERSION,
        "exported_at": timezone.now().isoformat(),
        "format": FORMAT.read_text(encoding="utf-8"),
        "categories": [{
            "id": category.pk,
            "name": category.name,
            "path": category.full_name,
            "parent": category.parent_category_id,
            "description": category.description,
            "keywords": category.keywords,
            "naming": category.naming,
            "items": category.item_count,
        } for category in categories],
        "items": [{
            "id": item.pk,
            "kind": item.kind,
            "name": item.name or "",
            "description": item.description,
            "category": item.category_id,
            "category_path": item.category.full_name if item.category else None,
            "barcodes": [{"id": barcode.pk, "data": barcode.data, "type": barcode.type.name if barcode.type else None}
                         for barcode in item.itembarcode_set.all()],
            "photos": [{"id": image.pk, "description": text(image.description), "text": text(image.ocr_text)}
                       for image in item.itemimage_set.all()],
            "files": [{"id": file.pk, "description": text(file.description)} for file in item.itemfile_set.all()
                      if text(file.description)],
        } for item in items],
    }
