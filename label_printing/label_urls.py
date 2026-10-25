"""What the QR codes on printed labels hold, and what is recorded about each printed label."""
from dataclasses import dataclass

from django.utils.formats import number_format

from inventory.label_ids import core, qr, services as label_ids
from inventory.models import LabelId

# Stands in for an item label's ID in previews, which must not use up IDs; same length, same QR size.
PREVIEW_CODE = "K7R4XD"


def location_url(location):
    """A location's code via the label host (HTTPS://I.ZAM.HAUS/WH-1.R303.A); codes stay (former codes too)."""
    return qr.location_content(location.unique_identifier)


def location_snapshot(location):
    return {"type": "location", "id": location.pk, "code": location.unique_identifier, "name": location.name,
            "qr": location_url(location)}


@dataclass
class ItemAt:
    """An item label's subject: the item, and the location it is stored at (if any)."""
    item: object
    location: object = None

    @property
    def pk(self):
        return self.item.pk

    def __str__(self):
        return f"{self.item.name} @ {self.location.unique_identifier}" if self.location else self.item.name


def label_id_content(code):
    """A label ID's QR code: HTTPS://I.ZAM.HAUS/K7R4XD."""
    return qr.url_prefix() + code


def item_qr(subject, code):
    """An item label's QR code: the item's label ID, then the code of the location it is stored at, uppercase so
    the QR code stays alphanumeric (HTTPS://I.ZAM.HAUS/K7R4XD/WH-1.R303.A); the resolver passes the location on
    to the item's page, which puts taking stock out there first. One ID serves every location."""
    content = label_id_content(code)
    return f"{content}/{subject.location.unique_identifier.upper()}" if subject.location is not None else content


def item_label_code(subject, user=None, create=True):
    """The item's label ID: the one it has, else a new one claimed for it (without create, e.g. for previews:
    None)."""
    existing = LabelId.objects.assigned().filter(item=subject.item).order_by("assigned_at", "code").first()
    if existing is not None or not create:
        return existing.code if existing else None
    return label_ids.generate_and_claim(subject.item, user, batch="print").code


def unique_item_label_id(unique_item):
    """The unique item's label ID, or None."""
    return LabelId.objects.assigned().filter(unique_item=unique_item).order_by("assigned_at", "code").first()


def unique_item_label_code(unique_item, user=None, create=True):
    """The code of the unique item's label ID: the one it has, else a new one claimed for it (without create,
    e.g. for previews: None)."""
    lid = unique_item_label_id(unique_item)
    if lid is not None or not create:
        return lid.code if lid else None
    return label_ids.generate_and_claim(unique_item, user, batch="print").code


def unique_item_snapshot(unique_item, code):
    return {"type": "uniqueitem", "id": unique_item.pk, "name": unique_item.item.name, "code": code,
            "owner": unique_item.owner_first_name_display or "", "qr": label_id_content(code)}


def price_amount(item):
    """"1,50" for items for sale with a price, else ""."""
    if not item.for_sale or item.sale_price is None:
        return ""
    return number_format(item.sale_price, 2, use_l10n=True)


def price_text(item):
    """"1,50 € / Stk" for items for sale with a price, else ""."""
    amount = price_amount(item)
    return f"{amount} € / {item.measurement_unit.short}" if amount else ""


def item_snapshot(subject, code):
    item = subject.item
    return {"type": "item", "id": item.pk, "name": item.name, "price": price_text(item),
            "sale_price": str(item.sale_price) if item.sale_price is not None else None,
            "location": subject.location.unique_identifier if subject.location else None,
            "location_id": subject.location.pk if subject.location else None,
            "code": code, "qr": item_qr(subject, code)}


def label_id_snapshot(lid):
    target = lid.target
    return {"type": "labelid", "code": lid.code, "status": lid.status,
            "target": str(lid.url or target or ""), "qr": label_id_content(lid.code)}


def display(code):
    return core.display(code)
