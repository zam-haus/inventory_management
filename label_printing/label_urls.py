"""What the QR codes on printed labels hold, and what is recorded about each printed label."""
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.urls import reverse
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


def item_target(subject):
    """Where an item label leads: the item's page for that location, with taking stock out at hand."""
    path = reverse("view_item", args=[subject.item.pk])
    if subject.location is not None:
        path += f"?loc={subject.location.pk}"
    return settings.DEFAULT_URL.rstrip("/") + path


def item_label_code(subject, user=None, create=True):
    """The label ID whose QR code leads to the item at its location: the one used before, else a new one
    (without create, e.g. for previews: None)."""
    url = item_target(subject)
    existing = LabelId.objects.filter(status=LabelId.Status.ASSIGNED, url=url).order_by("assigned_at", "code").first()
    if existing is not None or not create:
        return existing.code if existing else None
    with transaction.atomic():
        lid, = label_ids.generate_batch(1, batch="print", user=user)
        return label_ids.assign_url(lid.code, url, user).code


def price_text(item):
    """"1,50 € / Stk" for items for sale with a price, else ""."""
    if not item.for_sale or item.sale_price is None:
        return ""
    return f"{number_format(item.sale_price, 2, use_l10n=True)} € / {item.measurement_unit.short}"


def item_snapshot(subject, code):
    item = subject.item
    return {"type": "item", "id": item.pk, "name": item.name, "price": price_text(item),
            "sale_price": str(item.sale_price) if item.sale_price is not None else None,
            "location": subject.location.unique_identifier if subject.location else None,
            "location_id": subject.location.pk if subject.location else None,
            "code": code, "qr": label_id_content(code)}


def display(code):
    return core.display(code)
