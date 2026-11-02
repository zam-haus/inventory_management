"""What result lists show of each entry, loaded from the database in a fixed number of queries: the search results
and every other list of locations, categories, items and unique items (results/entries.html)."""
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from django.conf import settings
from django.db.models import (Case, Count, F, IntegerField, OuterRef, Prefetch, Q, Subquery, Value, When,
                              prefetch_related_objects)
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django.utils.translation import pgettext_lazy

from ..label_ids.lookup import annotate_label_code
from .. import location_display
from ..location_display import CATEGORY_ICONS, icon_name
from ..models import Category, Item, ItemImage, ItemLocation, Location, UniqueItem

SOURCE_LABELS = {
    "description": _("description"),
    "keywords": pgettext_lazy("found in", "keywords"),  # "Found in keywords: Spax"
    "category_keywords": pgettext_lazy("found in", "keywords of its category"),  # of an item or unique item
    "category": _("category"),
    "barcode": _("barcode"),
    "photo": _("photo description"),
    "photo_text": _("text on a photo"),
    "file": _("document"),
    "notes": _("notes"),
}
KINDS = {
    "location": ("geo-alt", _("Location")),
    "category": ("folder", _("Category")),
    "item": ("boxes", _("Item")),
    "unique": ("box-star", _("Unique item")),
}
SERIALIZED_ICON = "box-star-stack"  # a serialized item: several unique items (docs/icons.md)
# What the rows show as icons, drawn once per page (templatetags/search_tags.py: result_icon_sprite).
ICONS = {*(icon for icon, _label in KINDS.values()), SERIALIZED_ICON, *CATEGORY_ICONS.values()}
# Sub-locations in the counts, by icon_name: building parts and others, storage units, containers.
SUB_LOCATIONS = (
    ("geo-alt", lambda n: ngettext("%(count)s sub-location", "%(count)s sub-locations", n) % {"count": n}),
    ("bookshelf", lambda n: ngettext("%(count)s storage unit", "%(count)s storage units", n) % {"count": n}),
    ("eurobox-open", lambda n: ngettext("%(count)s container", "%(count)s containers", n) % {"count": n}),
)
MAX_PLACES = 3
ACTIVE_PLACE = {"location__is_deleted": False, "location__is_reserved": False}


@dataclass
class Place:
    location: Location
    amount: str = ""  # stock of an item, e.g. "3 pc"
    label: str = ""  # a unique item of an item, named as everywhere and linked to its page (unique_item_html)


@dataclass
class Tally:
    """A count with its icon, as the trees show them; `text` in words ("3 containers"), as tooltip and for screen
    readers."""
    icon: str
    number: int
    text: str


def tallies(below=None, items=0, unique=0):
    """What is in a location or category, as in the trees: its sub-locations (a Counter by icon_name), then its
    counted items, then its unique items; none that are 0."""
    below = below or Counter()
    found = [Tally(icon, below[icon], text(below[icon])) for icon, text in SUB_LOCATIONS if below[icon]]
    if items:
        found.append(Tally(KINDS["item"][0], items, count_text("item", items)))
    if unique:
        found.append(Tally(KINDS["unique"][0], unique, count_text("unique", unique)))
    return found


@dataclass
class Entry:
    kind: str
    obj: object
    title: str
    subtitle: str = ""
    code: str = ""  # a location's code
    label: str = ""  # a unique item's label ID, after its name
    number: int | None = None  # instead, the number of a unique item without one
    where: str = ""  # the path above a category
    above: list = field(default_factory=list)  # the locations above a location, from the top (shown with their icons)
    excerpt: str = ""  # what belongs in a category (Category.summary)
    counts: list = field(default_factory=list)  # Tallies: what is in a location or category, as in the trees
    photos: list = field(default_factory=list)  # (image file, description), the first one as thumbnail
    places: list = field(default_factory=list)
    more_places: int = 0
    sources: list = field(default_factory=list)  # where else the words were found, with the snippet found there
    snippets: dict = field(default_factory=dict)
    # The category of an item or unique item, named in the row; not where the list is grouped by it (a heading).
    category: object = None
    # Set by the list showing it: what it shows the entry for (e.g. its ItemLocation, for the amount and the
    # stock button), a heading before it ((title, url), lists by group), the group it belongs to (lists by category:
    # the category's pk, "none" without one; its heading shows the folder, a category's page folds it) and its
    # aria-current (the location an item label leads to).
    row: object = None
    at: object = None  # where the row is, in a list of a location's subtree (its items at a location below it)
    group: tuple = None
    group_key: str = ""
    group_sticky: bool = True  # False for a heading the breadcrumbs name already (a category's own items)
    current: str = ""

    @property
    def icon(self):
        if self.kind == "location":
            return icon_name(self.obj)
        if self.kind == "item" and self.obj.kind == Item.Kind.SERIALIZED:
            return SERIALIZED_ICON
        return KINDS[self.kind][0]

    @property
    def at_icon(self):
        return icon_name(self.at) if self.at else ""

    @property
    def where_icon(self):
        return KINDS["category"][0] if self.kind == "category" else "geo-alt"

    @property
    def category_path(self):
        return self.category.full_name.replace("/", " › ") if self.category else ""

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
        """The photos for the viewer below an entry (results.js): original files, loaded only when shown."""
        return json.dumps([{"src": image.url, "alt": description} for image, description in self.photos])


def count_text(kind, count, more=False):
    """How many hits of a kind there are, for the summary above the results: "12 items", "500+ items"."""
    texts = {
        "location": ngettext("%(count)s location", "%(count)s locations", count),
        "category": ngettext("%(count)s category", "%(count)s categories", count),
        "item": ngettext("%(count)s item", "%(count)s items", count),
        "unique": ngettext("%(count)s unique item", "%(count)s unique items", count),
    }
    return texts[kind] % {"count": f"{count}+" if more else count}


def sub_locations(locations):
    """{pk: Counter by icon_name} of the active locations below these, in their whole subtrees: counted by the database
    in one query, by their code paths (locatable_identifier, its prefix index), each to the innermost listed location
    it is below; a listed location inside another one then adds its count to that one's."""
    if not locations:
        return {}
    below = lambda location: Q(locatable_identifier__startswith=f"{location.locatable_identifier}.")
    innermost = sorted(locations, key=lambda location: -len(location.locatable_identifier))
    owner = Case(*[When(below(location), then=Value(location.pk)) for location in innermost],
                 output_field=IntegerField())
    rows = (Location.active.filter(reduce(or_, (below(location) for location in locations)))
            .annotate(owner=owner).values("owner", "type__category").annotate(n=Count("pk")).order_by())
    counted = defaultdict(Counter)
    for row in rows:
        counted[row["owner"]][CATEGORY_ICONS.get(row["type__category"], "geo-alt")] += row["n"]
    totals = {}
    for location in locations:
        totals[location.pk] = sum((counted[other.pk] for other in locations
                                   if other.locatable_identifier.startswith(f"{location.locatable_identifier}.")),
                                  Counter(counted[location.pk]))
    return totals


def photos(images):
    return [(image.image, image.description) for image in images]


def count_of(rows):
    """The number of rows per item, as a subquery on items."""
    return Coalesce(Subquery(rows.values("item").annotate(n=Count("pk")).values("n")), 0)


def prepare(kind, objects, here=None, item_photos=True, scope=None):
    """Loads what the entries of these objects show, in a fixed number of queries. With `here` (a location),
    places there are left out: the list is that location's; with `scope` (a condition on the place's location,
    Location.in_tree), those within it. item_photos=False leaves the item's general photos out of its unique items
    (on the item's page, which shows them above)."""
    objects = list(objects)
    if not objects:
        return
    if kind == "location":
        prefetch_related_objects(objects, "parent_location", "type")
        # The path above each, with the icons of the locations in it: in one query for the list.
        above = location_display.paths(objects)
        for location in objects:
            location.entry_above = above[location.pk]
        # As in the location tree: the sub-locations in its whole subtree, the items and unique items right there.
        pks = [location.pk for location in objects]
        stock = dict(ItemLocation.objects.filter(location__in=pks, item__is_deleted=False).values("location")
                     .annotate(n=Count("pk")).values_list("location", "n"))
        unique = dict(UniqueItem.active.filter(location__in=pks).values("location").annotate(n=Count("pk"))
                      .values_list("location", "n"))
        below = sub_locations(objects)
        for location in objects:
            location.entry_counts = tallies(below[location.pk], stock.get(location.pk, 0), unique.get(location.pk, 0))
    elif kind == "item":
        places = ItemLocation.objects.filter(**ACTIVE_PLACE)
        unique_items = UniqueItem.active.all()
        if scope is not None:
            places, unique_items = places.exclude(scope), unique_items.exclude(scope)
        elif here is not None:
            places, unique_items = places.exclude(location=here), unique_items.exclude(location=here)
        # A few places each (items may be in hundreds), and how many there are in all.
        prefetch_related_objects(
            objects,
            Prefetch("itemlocation_set", to_attr="entry_places", queryset=places.select_related(
                "location__type", "item__measurement_unit").order_by("location__locatable_identifier", "pk")[:MAX_PLACES]),
            Prefetch("unique_items", to_attr="entry_unique_items", queryset=annotate_label_code(
                unique_items.select_related("location__type")).order_by("location__locatable_identifier", "pk")[:MAX_PLACES]),
            # The item's own photos first, then those of its unique items still in the inventory.
            Prefetch("itemimage_set", to_attr="entry_images", queryset=ItemImage.objects.filter(
                Q(unique_item__isnull=True) | Q(unique_item__disposed_at__isnull=True)).order_by(
                F("unique_item_id").asc(nulls_first=True), "-is_primary", "pk")),
        )
        counts = dict(Item.objects.filter(pk__in=[item.pk for item in objects]).annotate(
            n=count_of(places.filter(item=OuterRef("pk"))) + count_of(unique_items.filter(item=OuterRef("pk")))
        ).values_list("pk", "n"))
        for item in objects:
            item.entry_place_count = counts.get(item.pk, 0)
        prefetch_related_objects(objects, "category")
    elif kind == "unique":
        prefetch_related_objects(objects, "item__category", "location__type", Prefetch(
            "images", to_attr="entry_images", queryset=ItemImage.objects.order_by("-is_primary", "pk")))
        if item_photos:
            prefetch_related_objects(objects, Prefetch(
                "item__itemimage_set", to_attr="entry_general_images",
                queryset=ItemImage.objects.filter(unique_item__isnull=True).order_by("-is_primary", "pk")))
        missing = [unique_item for unique_item in objects if "_label_code" not in unique_item.__dict__]
        if missing:
            codes = dict(annotate_label_code(UniqueItem.objects.filter(pk__in=[u.pk for u in missing]))
                         .values_list("pk", "label_code"))
            for unique_item in missing:
                unique_item.label_code = codes.get(unique_item.pk)
    elif kind == "category":
        # As in the item tree: counted items and unique items, those below it included, added up per category.
        bulk = dict(Item.active.filter(category__isnull=False).exclude(kind=Item.Kind.SERIALIZED).values("category")
                    .annotate(n=Count("pk")).values_list("category", "n"))
        unique = dict(UniqueItem.active.filter(item__is_deleted=False, item__category__isnull=False)
                      .values("item__category").annotate(n=Count("pk")).values_list("item__category", "n"))
        paths = dict(Category.objects.values_list("pk", "full_name"))
        for category in objects:
            tree = [pk for pk, path in paths.items() if pk == category.pk or path.startswith(f"{category.full_name}/")]
            category.entry_counts = tallies(items=sum(bulk.get(pk, 0) for pk in tree),
                                            unique=sum(unique.get(pk, 0) for pk in tree))


def load(hits):
    """{(kind, pk): object} for the hits, with what the entries show."""
    pks = {kind: [hit.pk for hit in hits if hit.kind == kind] for kind in KINDS}
    querysets = {
        "location": Location.active.select_related("parent_location", "type"),
        "category": Category.objects.all(),
        "item": Item.active.select_related("category"),
        "unique": annotate_label_code(UniqueItem.active.select_related("item__category", "location")),
    }
    found = {}
    for kind, queryset in querysets.items():
        if pks[kind]:
            objects = list(queryset.filter(pk__in=pks[kind]))
            prepare(kind, objects)
            found.update({(kind, obj.pk): obj for obj in objects})
    return found


def entry(kind, obj, hit=None, here=None):
    """The entry of a prepared object; `hit` adds where the search words were found."""
    labels = {**SOURCE_LABELS, "label": settings.LABEL_ID_NAME}  # its label ID, by the name it has here (ZAMid)
    snippets = hit.snippets if hit else {}
    sources = [f"{labels[source]}: {snippets[source]}" if snippets.get(source) else labels[source]
               for source in (hit.sources if hit else ()) if source in labels]
    common = {"kind": kind, "obj": obj, "sources": sources, "snippets": snippets}
    if kind == "location":
        # In the lists of a location's page, the path above it down to that location is the page's.
        above = getattr(obj, "entry_above", [])
        if here is not None and here.pk in [step.pk for step in above]:
            above = above[[step.pk for step in above].index(here.pk) + 1:]
        return Entry(title=obj.title, subtitle=obj.subtitle, code=obj.unique_identifier, above=above,
                     counts=obj.entry_counts, photos=[(obj.overview_photo, obj.title)] if obj.overview_photo else [], **common)
    if kind == "category":
        return Entry(title=obj.name, where=obj.full_name.rpartition("/")[0].replace("/", " › "),
                     excerpt=obj.summary, counts=obj.entry_counts, **common)
    if kind == "item":
        places = [Place(entry.location, amount=entry.amount_text) for entry in obj.entry_places]
        places += [Place(unique_item.location, label=location_display.unique_item_html(
                       unique_item, url=unique_item.get_absolute_url(), icon=False))
                   for unique_item in obj.entry_unique_items]
        return Entry(title=str(obj), photos=photos(obj.entry_images), places=places[:MAX_PLACES],
                     more_places=max(0, obj.entry_place_count - MAX_PLACES), category=obj.category, **common)
    images = obj.entry_images + getattr(obj.item, "entry_general_images", [])
    return Entry(title=obj.title, label=obj.label_display,
                 number=None if obj.label_code else obj.pk,
                 photos=photos(images), places=[] if obj.location == here else [Place(obj.location)],
                 category=obj.item.category, **common)


def entries(hits, here=None):
    """The entries of the hits, in their order; hits whose object is gone (e.g. deleted since) are left out. With
    `here`, as in that location's lists."""
    found = load(hits)
    return [entry(hit.kind, found[hit.kind, hit.pk], hit, here=here) for hit in hits if (hit.kind, hit.pk) in found]


def group_by_category(entries, previous=False):
    """A heading wherever the category changes, in a list of items sorted by it (a location's items); the rows then
    name no category. Items without one come last, under "Without category". `previous`: the category of the row
    before them (None: none), where they continue a list (its further rows, views.location_rows)."""
    for entry in entries:
        category = entry.category
        if previous is False or (category and category.pk) != (previous and previous.pk):
            entry.group = (category.name, category.get_absolute_url()) if category else (_("Without category"), "")
        entry.group_key = str(category.pk) if category else "none"
        entry.category = None
        previous = category
    return entries


def listed(kind, objects, here=None, item_photos=True, scope=None, hits=None):
    """The entries of a list that is no search (a location's items, an item's places, …), in the objects' order;
    with `hits` ({pk: Hit}), where the search found them, too."""
    objects = list(objects)
    prepare(kind, objects, here=here, item_photos=item_photos, scope=scope)
    return [entry(kind, obj, (hits or {}).get(obj.pk), here=here) for obj in objects]
