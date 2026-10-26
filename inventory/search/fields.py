"""
What the search may find (docs/search.md): the fields wanted here, and of them only those the public export
keeps as they are (public_export.publishable), in the rows it exports (public_export.export_filter).
Whatever the export replaces or leaves out, such as purchase prices, owners and their contact details or
internal files, is never searched. A new field is searched only once it is listed here.
"""
from django.db.models import Q

from ..public_export import export_filter, publishable

WANTED = {
    "inventory.location": ("name", "short_name", "purpose", "physical_description",
                           "unique_identifier", "locatable_identifier", "descriptive_identifier"),
    "inventory.item": ("name", "description"),
    "inventory.category": ("name",),
    "inventory.itembarcode": ("data",),
    "inventory.itemimage": ("description", "ocr_text"),
    "inventory.itemfile": ("description",),
    "inventory.uniqueitem": ("name", "notes"),
}


def searchable(model, field):
    label = model._meta.label_lower
    return field in WANTED.get(label, ()) and publishable(label, field)


def exported_rows(model):
    """The rows of the model the export keeps, as a Q (e.g. no internal files)."""
    return Q(**export_filter(model._meta.label_lower))
