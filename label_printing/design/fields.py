"""The {fields} of label designs per kind of label, their values for a subject, and sample records."""
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

from inventory.label_ids import naming, qr
from inventory.models import Item, LabelId, Location
from .. import label_urls


@dataclass(frozen=True)
class Field:
    name: str
    help: str


FIELDS = {
    "location": [
        Field("code", _("the location's code, e.g. WH-1.R303.a")),
        Field("qr", _("for QR codes: the code via the label host, HTTPS://I.ZAM.HAUS/WH-1.R303.A")),
        Field("name", _("the location's name")),
        Field("path", _("where it is: the full path with codes")),
        Field("purpose", _("its purpose")),
        Field("short", _("the code within its area, e.g. R303.a")),
    ],
    "item": [
        Field("name", _("the item's name")),
        Field("price", _("price per unit for items for sale, e.g. 0,15 € / Stk; else empty")),
        Field("qr", _("for QR codes: its label ID, leading to the item at the location")),
        Field("location", _("the location's code")),
        Field("id", _("the label ID as printed, e.g. K7R-4XD")),
        Field("unit", _("the unit, e.g. Stk")),
    ],
    "labelid": [
        Field("id", _("the label ID as printed, e.g. K7R-4XD")),
        Field("id1", _("its first part, e.g. K7R")),
        Field("id2", _("its second part, e.g. 4XD")),
        Field("qr", _("for QR codes: the label ID via the label host")),
        Field("idname", _("what label IDs are called, e.g. ZAMid")),
        Field("target", _("what the ID belongs to")),
    ],
}


def names(subject_type):
    return [field.name for field in FIELDS.get(subject_type, [])]


def location_values(location):
    return {"code": location.unique_identifier, "qr": label_urls.location_url(location), "name": location.name,
            "path": location.descriptive_identifier, "purpose": location.purpose or "",
            "short": location.locatable_identifier}


def item_values(subject, code):
    item = subject.item
    return {"name": item.name, "price": label_urls.price_text(item), "qr": label_urls.label_id_content(code),
            "location": subject.location.unique_identifier if subject.location else "",
            "id": label_urls.display(code), "unit": item.measurement_unit.short}


def label_id_values(lid):
    first, _dash, second = lid.display.partition("-")
    return {"id": lid.display, "id1": first, "id2": second, "qr": qr.url_prefix() + lid.code,
            "idname": naming.name(), "target": str(lid.url or lid.target or "")}


def sample_records(subject_type, limit=5):
    """A few real records to preview designs with: [(name, values)]. Previews hand out no label IDs."""
    if subject_type == "location":
        locations = Location.active.exclude(parent_location=None).order_by("-pk")[:limit]
        return [(location.unique_identifier, location_values(location)) for location in locations]
    if subject_type == "item":
        records = []
        for item in Item.active.filter(kind=Item.Kind.BULK).select_related("measurement_unit").order_by("-pk")[:limit]:
            subject = label_urls.ItemAt(item, Location.active.filter(itemlocation__item=item).first())
            code = label_urls.item_label_code(subject, create=False) or label_urls.PREVIEW_CODE
            records.append((item.name, item_values(subject, code)))
        return records
    if subject_type == "labelid":
        lids = LabelId.objects.filter(status=LabelId.Status.ASSIGNED).order_by("-assigned_at")[:limit]
        return [(lid.display, label_id_values(lid)) for lid in lids]
    return []
