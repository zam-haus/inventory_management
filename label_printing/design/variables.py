"""
The variables of label designs per kind of label (texts.py): the label's subject itself, so templates use its
fields and properties, and the QR code's content; their values for a subject, samples and sample records.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from inventory.label_ids import naming
from inventory.models import Item, LabelId, Location
from .. import label_urls


@dataclass(frozen=True)
class Variable:
    expression: str
    help: str


# What a template's page lists for each kind of label: the variables, and what is used most of them.
VARIABLES = {
    "location": [
        Variable("location", _("the location, with all its fields and properties, e.g.:")),
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


def label_id_variables(lid):
    return {**common(), "label_id": lid, "qr": label_urls.label_id_content(lid.code)}


def samples(subject_type):
    """Variables of typical length without records: whether a template's QR code fits a printer's labels at all,
    and its picture in the list of templates."""
    location = {"unique_identifier": "WH-1.R303.a", "name": "Fach a", "descriptive_identifier": "R303.a",
                "locatable_identifier": "R303.a", "purpose": ""}
    label_id = LabelId(code=label_urls.PREVIEW_CODE)
    if subject_type == "location":
        return {**common(), "location": location, "qr": "HTTPS://I.ZAM.HAUS/WH-1.R303.A"}
    if subject_type == "item":
        item = {"name": "Artikel", "sale_price": Decimal("0.15"), "for_sale": True, "measurement_unit": {"short": "Stk"}}
        return {**common(), "item": item, "location": location, "label_id": label_id,
                "qr": "HTTPS://I.ZAM.HAUS/K7R4XD/WH-1.R303.A"}
    if subject_type == "labelid":
        return {**common(), "label_id": label_id, "qr": "HTTPS://I.ZAM.HAUS/K7R4XD"}
    return common()


def sample_records(subject_type, limit=5):
    """A few real records to preview designs with: [(name, variables)]. Previews hand out no label IDs."""
    if subject_type == "location":
        locations = Location.active.exclude(parent_location=None).order_by("-pk")[:limit]
        return [(location.unique_identifier, location_variables(location)) for location in locations]
    if subject_type == "item":
        records = []
        for item in Item.active.filter(kind=Item.Kind.BULK).select_related("measurement_unit").order_by("-pk")[:limit]:
            subject = label_urls.ItemAt(item, Location.active.filter(itemlocation__item=item).first())
            code = label_urls.item_label_code(subject, create=False) or label_urls.PREVIEW_CODE
            records.append((item.name, item_variables(subject, code)))
        return records
    if subject_type == "labelid":
        lids = LabelId.objects.filter(status=LabelId.Status.ASSIGNED).order_by("-assigned_at")[:limit]
        return [(lid.display, label_id_variables(lid)) for lid in lids]
    return []
