"""
The variables of label designs per kind of label (texts.py): the label's subject itself, so templates use its
fields and properties, and the QR code's content; their values for a subject, real records to show designs with,
and made-up ones (Placeholder) where there are none.
"""
import zlib
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

from inventory.label_ids import naming
from inventory.models import Item, LabelId, Location, UniqueItem
from .. import label_urls


@dataclass(frozen=True)
class Variable:
    expression: str
    help: str


# What a template's page lists for each kind of label: the variables, and what is used most of them.
VARIABLES = {
    "location": [
        Variable("location", _("the location, with all its fields and properties, e.g.:")),
        Variable("location.title", _("what it is called first: its purpose, else its name")),
        Variable("location.unique_identifier", _("its code, e.g. WH-1.R303.a")),
        Variable("location.name", _("its name")),
        Variable("location.descriptive_identifier", _("where it is: the full path with codes")),
        Variable("location.locatable_identifier", _("the code within its area, e.g. R303.a")),
        Variable("location.purpose", _("its purpose")),
        Variable("location.parent_location.name", _("the name of the location it is in")),
        Variable("qr", _("for QR codes: the code via the label host, HTTPS://I.ZAM.HAUS/WH-1.R303.A")),
    ],
    "item": [
        Variable("item", _("the item, with all its fields and properties, e.g.:")),
        Variable("item.name", _("its name")),
        Variable("item.sale_price|floatformat:2", _("its price for items for sale, e.g. 0,15; else empty")),
        Variable("item.measurement_unit.short", _("its unit, e.g. Stk")),
        Variable("location.unique_identifier", _("the code of the location it is stored at (the first one); "
                                                 "location is the location, if there is one")),
        Variable("label_id", _("its label ID as printed, e.g. K7R-4XD")),
        Variable("qr", _("for QR codes: the item's label ID and the location's code (…/K7R4XD/WH-1.R303.A), "
                         "leading to the item there")),
    ],
    "uniqueitem": [
        Variable("unique_item", _("the unique item, with all its fields and properties, e.g.:")),
        Variable("unique_item.owner_first_name_display", _("its owner's first name, if it is not the ZAM's")),
        Variable("unique_item.has_owner", _("whether it has an owner other than the ZAM (for rules)")),
        Variable("item.name", _("what it is: the item's name")),
        Variable("location.unique_identifier", _("the code of the location it is at")),
        Variable("label_id", _("its label ID as printed, e.g. K7R-4XD")),
        Variable('label_id.code|slice:":3"', _("its first part, e.g. K7R")),
        Variable('label_id.code|slice:"3:"', _("its second part, e.g. 4XD")),
        Variable("qr", _("for QR codes: the label ID via the label host")),
    ],
    "labelid": [
        Variable("label_id", _("the label ID as printed, e.g. K7R-4XD")),
        Variable('label_id.code|slice:":3"', _("its first part, e.g. K7R")),
        Variable('label_id.code|slice:"3:"', _("its second part, e.g. 4XD")),
        Variable("label_id.target", _("what it belongs to")),
        Variable("qr", _("for QR codes: the label ID via the label host")),
    ],
}
COMMON = [Variable("label_id_name", _("what label IDs are called, e.g. ZAMid"))]


def common():
    return {"label_id_name": naming.name()}


def location_variables(location):
    return {**common(), "location": location, "qr": label_urls.location_url(location)}


def item_variables(subject, code):
    """For an item at a location (label_urls.ItemAt) and the code of its label ID (in previews a stand-in)."""
    label_id = LabelId.objects.filter(code=code).first() or LabelId(code=code)
    return {**common(), "item": subject.item, "location": subject.location, "label_id": label_id,
            "qr": label_urls.item_qr(subject, code)}


def unique_item_variables(unique_item, code):
    """For a unique item and the code of its label ID (in previews a stand-in)."""
    label_id = LabelId.objects.filter(code=code).first() or LabelId(code=code)
    return {**common(), "unique_item": unique_item, "item": unique_item.item, "location": unique_item.location,
            "label_id": label_id, "qr": label_urls.label_id_content(code)}


def label_id_variables(lid):
    return {**common(), "label_id": lid, "qr": label_urls.label_id_content(lid.code)}


LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et "
         "dolore magna aliqua").split()


class Placeholder(str):
    """A made-up record where there is none: any attribute is another placeholder, its text two words of lorem
    ipsum and its number (float, int: for filters like floatformat) a random one; always the same for the same
    name, so whether a template fits a printer's labels does not change from one try to the next."""

    def __new__(cls, name):
        seed = zlib.crc32(name.encode())
        words = (LOREM[(seed + offset) % len(LOREM)] for offset in range(2))
        placeholder = super().__new__(cls, " ".join(words).capitalize())
        placeholder._name = name
        return placeholder

    def __getattr__(self, attribute):
        if attribute.startswith("_"):
            raise AttributeError(attribute)
        return Placeholder(f"{self._name}.{attribute}")

    def __float__(self):
        return zlib.crc32(self._name.encode()) % 10000 / 100

    def __int__(self):
        return zlib.crc32(self._name.encode()) % 1000


def placeholders(subject_type):
    """The variables of a made-up subject (Placeholder): whether a template's QR code fits a printer's labels at
    all, and how a template looks where there are no records of its kind."""
    code = label_urls.PREVIEW_CODE
    if subject_type == "location":
        return location_variables(Placeholder("location"))
    if subject_type == "item":
        return item_variables(label_urls.ItemAt(Placeholder("item"), Placeholder("location")), code)
    if subject_type == "uniqueitem":
        return unique_item_variables(Placeholder("unique_item"), code)
    if subject_type == "labelid":
        return label_id_variables(LabelId(code=code))
    return common()


def sample_subjects(subject_type, limit=5, shuffled=False):
    """A few real subjects to show designs with, the newest or random ones: [(name, subject)]; items at their
    first location."""
    order = "?" if shuffled else None
    if subject_type == "location":
        locations = Location.active.exclude(parent_location=None).order_by(order or "-pk")[:limit]
        return [(location.unique_identifier, location) for location in locations]
    if subject_type == "item":
        items = Item.active.filter(kind=Item.Kind.BULK).select_related("measurement_unit").order_by(order or "-pk")
        return [(item.name, label_urls.ItemAt(item, Location.active.filter(itemlocation__item=item)
                                              .order_by("unique_identifier").first()))
                for item in items[:limit]]
    if subject_type == "uniqueitem":
        unique_items = UniqueItem.active.select_related("item", "location").order_by(order or "-pk")[:limit]
        return [(str(unique_item), unique_item) for unique_item in unique_items]
    if subject_type == "labelid":
        lids = LabelId.objects.filter(status=LabelId.Status.ASSIGNED).order_by(order or "-assigned_at")[:limit]
        return [(lid.display, lid) for lid in lids]
    return []
