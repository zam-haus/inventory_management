"""What the search results show of each hit, loaded from the database in a fixed number of queries."""
import json
from dataclasses import dataclass, field

from django.db.models import F, Prefetch, Q
from django.utils.translation import gettext_lazy as _

from ..label_ids.lookup import annotate_label_code
from ..models import Item, ItemImage, ItemLocation, Location, LocationType, UniqueItem

SOURCE_LABELS = {
    "description": _("description"),
    "category": _("category"),
    "barcode": _("barcode"),
    "photo": _("photo description"),
    "photo_text": _("text on a photo"),
    "file": _("document"),
    "notes": _("notes"),
}
KINDS = {
    "location": ("geo-alt", _("Location")),
    "item": ("boxes", _("Item")),
    "unique": ("box-star", _("Unique item")),
}
# Locations by what they are (LocationType.category); others, such as rooms, keep the pin.
LOCATION_ICONS = {
    LocationType.Category.STORAGE_UNIT: "bookshelf",
    LocationType.Category.CONTAINER: "eurobox-open",
}
MAX_PLACES = 3


@dataclass
class Place:
    location: Location
    amount: str = ""  # stock of an item, e.g. "3 pc"
    label: str = ""  # a unique item's label ID


@dataclass
class Entry:
    kind: str
    obj: object
    title: str
    subtitle: str = ""
    code: str = ""  # a location's code
    where: str = ""  # the path above a location
    photos: list = field(default_factory=list)  # (image file, description), the first one as thumbnail
    places: list = field(default_factory=list)
    more_places: int = 0
    sources: list = field(default_factory=list)
    snippets: dict = field(default_factory=dict)

    @property
    def icon(self):
        if self.kind == "location":
            return LOCATION_ICONS.get(self.obj.type.category, KINDS["location"][0])
        return KINDS[self.kind][0]

    @property
    def kind_label(self):
        return KINDS[self.kind][1]

    @property
    def url(self):
        return self.obj.get_absolute_url()

    @property
    def thumbnail(self):
        return self.photos[0][0] if self.photos else None

    @property
    def photos_json(self):
        """The photos for the viewer below a result (search.js): original files, loaded only when shown."""
        return json.dumps([{"src": image.url, "alt": description} for image, description in self.photos])


def photos(images):
    return [(image.image, image.description) for image in images]


def load(hits):
    """{(kind, pk): object} for the hits, with what the entries show."""
    pks = {kind: [hit.pk for hit in hits if hit.kind == kind] for kind in ("location", "item", "unique")}
    found = {}
    if pks["location"]:
        for location in Location.active.filter(pk__in=pks["location"]).select_related("parent_location", "type"):
            found["location", location.pk] = location
    if pks["item"]:
        active_place = {"location__is_deleted": False, "location__is_reserved": False}
        items = Item.active.filter(pk__in=pks["item"]).prefetch_related(
            Prefetch("itemlocation_set", to_attr="search_places", queryset=ItemLocation.objects.filter(
                **active_place).select_related("location", "item__measurement_unit").order_by(
                "location__locatable_identifier")),
            Prefetch("unique_items", to_attr="search_unique_items", queryset=annotate_label_code(
                UniqueItem.active.select_related("location")).order_by("location__locatable_identifier", "pk")),
            # The item's own photos first, then those of its unique items still in the inventory.
            Prefetch("itemimage_set", to_attr="search_images", queryset=ItemImage.objects.filter(
                Q(unique_item__isnull=True) | Q(unique_item__disposed_at__isnull=True)).order_by(
                F("unique_item_id").asc(nulls_first=True), "-is_primary", "pk")),
        )
        for item in items:
            found["item", item.pk] = item
    if pks["unique"]:
        unique_items = annotate_label_code(UniqueItem.active.filter(pk__in=pks["unique"])).select_related(
            "item", "location").prefetch_related(Prefetch("images", to_attr="search_images"))
        for unique_item in unique_items:
            found["unique", unique_item.pk] = unique_item
    return found


def entry(hit, obj):
    sources = [SOURCE_LABELS[source] for source in hit.sources if source in SOURCE_LABELS]
    common = {"kind": hit.kind, "obj": obj, "sources": sources, "snippets": hit.snippets}
    if hit.kind == "location":
        parent = obj.parent_location
        return Entry(title=obj.title, subtitle=obj.subtitle, code=obj.unique_identifier,
                     where=parent.descriptive_identifier if parent else "",
                     photos=[(obj.overview_photo, obj.title)] if obj.overview_photo else [], **common)
    if hit.kind == "item":
        places = [Place(entry.location, amount=entry.amount_text) for entry in obj.search_places]
        places += [Place(unique_item.location, label=unique_item.label_display or f"#{unique_item.pk}")
                   for unique_item in obj.search_unique_items]
        return Entry(title=str(obj), photos=photos(obj.search_images), places=places[:MAX_PLACES],
                     more_places=max(0, len(places) - MAX_PLACES), **common)
    return Entry(title=str(obj.item), subtitle=obj.name, photos=photos(obj.search_images),
                 places=[Place(obj.location, label=obj.label_display)], **common)


def entries(hits):
    """The entries of the hits, in their order; hits whose object is gone (e.g. deleted since) are left out."""
    found = load(hits)
    return [entry(hit, found[hit.kind, hit.pk]) for hit in hits if (hit.kind, hit.pk) in found]
