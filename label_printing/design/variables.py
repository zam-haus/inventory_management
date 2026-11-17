"""
The variables of label designs per kind of label (texts.py): the label's subject itself, so templates use its
fields and properties, and the QR code's content; their values for a subject, real records to show designs with,
and made-up ones (Placeholder) where there are none.
"""
import functools
import re
import zlib
from dataclasses import dataclass

from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext_lazy as _

from inventory.label_ids import naming
from inventory.label_ids.lookup import annotate_label_code
from inventory.models import Item, ItemLocation, LabelId, Location, UniqueItem
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
        Variable("location.locatable_identifier", _("the short names from the top-level location down, e.g. "
                                                    "HH-1.SK.K0520 (not on labels: use the code)")),
        Variable("location.purpose", _("its purpose")),
        Variable("location.parent_location.name", _("the name of the location it is in")),
        Variable("qr", _("for QR codes: the code via the label host, HTTPS://I.ZAM.HAUS/WH-1.R303.A")),
        Variable("contents", _("for list: what is right at the location: the locations in it with their code, its "
                               "items with their amount and its unique items with their label ID and whose they are, "
                               "if not the ZAM's")),
        Variable("responsible", _("the teams responsible for it (also from a location above it), e.g. Holzwerkstatt")),
        Variable("owner", _("whose what is at it is, if it is all one owner's other than the ZAM: the first name; empty "
                            "for the ZAM's")),
        Variable("owned", _("whether anything right at it has an owner: items or unique items (not just locations in "
                            "it)")),
        Variable("owners_differ", _("whether what is at it belongs to different owners (then contents marks whose each "
                                    "unique item is, if not the ZAM's)")),
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
        Variable("unique_item.name", _("its own name, if it has one, to tell it apart")),
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
COMMON = [Variable("label_id_name", _("what label IDs are called, e.g. ZAMid")),
          Variable("page", _("the number of the label, if a list goes on on further labels (else 1)")),
          Variable("pages", _("how many labels it takes (else 1)"))]


def common():
    return {"label_id_name": naming.name(), "page": 1, "pages": 1}


@dataclass(frozen=True)
class Entry:
    """A line of a list (layout.py): an item's amount ("12 Stk", "~5 Stk", "few Stk"; a bullet for unique items, empty
    for locations), its name, a unique item's label ID as printed or a location's code, and a note after them (whose a
    unique item is, if not the ZAM's)."""
    amount: str
    name: str
    code: str = ""
    note: str = ""

    def __str__(self):
        return " ".join(part for part in (self.amount, self.name, self.code, self.note) if part)


def owned_by(unique_item):
    """Whose the unique item is, if not the ZAM's: "Fremdeigentum: Erika"; only the first name, which is public (the
    contact of owners without an account is not)."""
    if not unique_item.has_owner:
        return ""
    name = unique_item.owner_first_name_display
    return str(_("not the ZAM's: %(name)s") % {"name": name} if name else _("not the ZAM's"))


UNIQUE = "•"  # in the amounts' column of a list: one thing


def owner_key(unique_item):
    """Who owns the unique item: None for the ZAM, else its owner's account or details."""
    if not unique_item.has_owner:
        return None
    return unique_item.owner_user_id or (unique_item.owner_first_name, unique_item.owner_contact)


def owners(unique_items, stock):
    """Who owns what is at a location (owner_key); items (`stock`) are the ZAM's."""
    return {owner_key(unique_item) for unique_item in unique_items} | ({None} if stock else set())


def ownership(location):
    """(owned, owner, differ) of what is right at the location: whether there are items or unique items at all,
    whether they belong to different owners (items are the ZAM's), and if not, whose they are when not the ZAM's:
    the first name ("not the ZAM's" without a public one); "" for the ZAM's."""
    unique_items = list(UniqueItem.active.filter(location=location).select_related("owner_user"))
    found = owners(unique_items, ItemLocation.objects.filter(location=location, item__is_deleted=False).exists())
    if len(found) > 1:
        return True, "", True
    foreign = next((unique_item for unique_item in unique_items if unique_item.has_owner), None)
    return bool(found), (str(foreign.owner_first_name_display or _("not the ZAM's")) if foreign else ""), False


def location_contents(location):
    """What is right at the location: the locations in it (a pallet's cartons) by code, then by name its items with
    their amount (none for quick items) and its unique items with their label ID, and whose they are if the contents
    belong to different owners (else the label says it once: owner)."""
    children = Location.active.filter(parent_location=location).order_by("unique_identifier")
    stock = (ItemLocation.objects.filter(location=location, item__is_deleted=False)
             .select_related("item__measurement_unit"))
    entries = [(entry.item.name, Entry(entry.amount_text if entry.amount is not None else "", entry.item.name))
               for entry in stock]
    unique_items = annotate_label_code(UniqueItem.active.filter(location=location).select_related("item", "owner_user"))
    differ = len(owners(unique_items, stock)) > 1
    entries += [(unique_item.title, Entry(UNIQUE, unique_item.title, unique_item.label_display,
                                          owned_by(unique_item) if differ else ""))
                for unique_item in unique_items]
    return ([Entry("", child.title, child.unique_identifier) for child in children]
            + [entry for _name, entry in sorted(entries, key=lambda pair: natural_key(pair[0]))])


def natural_key(text):
    """Numbers by their value: "Bartschlüssel 2" before "Bartschlüssel 10"."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.split(r"(\d+)", text.casefold()) if part]


def location_variables(location):
    owned = functools.cache(lambda: ownership(location))
    return {**common(), "location": location, "qr": label_urls.location_url(location),
            "contents": SimpleLazyObject(lambda: location_contents(location)),
            "responsible": SimpleLazyObject(lambda: ", ".join(str(team) for team in location.effective_responsible_teams)),
            "owned": SimpleLazyObject(lambda: owned()[0]), "owner": SimpleLazyObject(lambda: owned()[1]),
            "owners_differ": SimpleLazyObject(lambda: owned()[2])}


def item_variables(subject, code):
    """For an item at a location (label_urls.ItemAt) and the code of its label ID (in previews a stand-in); `code`
    may be a function, so that the label ID is only looked up when a label or rule uses it."""
    if callable(code):
        code = functools.cache(code)
        return {**common(), "item": subject.item, "location": subject.location,
                "label_id": SimpleLazyObject(lambda: LabelId.objects.filter(code=code()).first() or LabelId(code=code())),
                "qr": SimpleLazyObject(lambda: label_urls.item_qr(subject, code()))}
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
        return {**location_variables(Placeholder("location")),
                "contents": [Entry(f"{index + 1} {Placeholder('unit')}", Placeholder(f"entry {index}"),
                                   label_urls.PREVIEW_CODE if index == 2 else "") for index in range(3)],
                "responsible": Placeholder("responsible"), "owned": True, "owner": Placeholder("owner"),
                "owners_differ": False}
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
