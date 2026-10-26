"""
The search in the database (icontains), for development and small installations without a search
service (docs/search.md). Every word must match an entry: its own text (name, description, photos, …)
or the path of where it is (the names of its location and of the locations above). At least one word
must match the entry itself, so that searching a room does not list everything stored in it.
"""
from dataclasses import dataclass
from functools import reduce
from operator import or_
from typing import Callable

from django.db.models import BooleanField, Case, Exists, F, OuterRef, Q, Value, When
from django.db.models.functions import Coalesce, Lower, NullIf

from ..models import Category, Item, ItemBarcode, ItemFile, ItemImage, ItemLocation, Location, UniqueItem
from .base import NAME_KEYS, Hit
from .fields import exported_rows, searchable


@dataclass(frozen=True)
class Source:
    key: str  # what a hit is shown as (render.SOURCE_LABELS); NAME_KEYS count as a hit on the name
    model: type  # the model and field holding the text, checked by fields.searchable
    field: str
    match: Callable[[str], Q]  # one word, on the searched queryset


def related(model, owner, *conditions, **lookups):
    """Whether a related row the export keeps matches, e.g. a photo of the item."""
    return Exists(model.objects.filter(exported_rows(model), *conditions, **{owner: OuterRef("pk")}, **lookups))


def any_of(conditions):
    return reduce(or_, conditions)


GENERAL = Q(unique_item__isnull=True)  # photos and files of the item itself, not of one of its unique items
ACTIVE_LOCATION = {"location__is_deleted": False, "location__is_reserved": False}

ITEM_SOURCES = [
    Source("name", Item, "name", lambda w: Q(name__icontains=w)),
    Source("description", Item, "description", lambda w: Q(description__icontains=w)),
    Source("category", Category, "name", lambda w: Q(category__name__icontains=w)),
    Source("barcode", ItemBarcode, "data", lambda w: related(ItemBarcode, "item", data__icontains=w)),
    Source("photo", ItemImage, "description", lambda w: related(ItemImage, "item", GENERAL, description__icontains=w)),
    Source("photo_text", ItemImage, "ocr_text", lambda w: related(ItemImage, "item", GENERAL, ocr_text__icontains=w)),
    Source("file", ItemFile, "description", lambda w: related(ItemFile, "item", GENERAL, description__icontains=w)),
]

UNIQUE_SOURCES = [
    Source("name", Item, "name", lambda w: Q(item__name__icontains=w)),
    Source("name", UniqueItem, "name", lambda w: Q(name__icontains=w)),
    Source("category", Category, "name", lambda w: Q(item__category__name__icontains=w)),
    Source("notes", UniqueItem, "notes", lambda w: Q(notes__icontains=w)),
    Source("photo", ItemImage, "description", lambda w: related(ItemImage, "unique_item", description__icontains=w)),
    Source("photo_text", ItemImage, "ocr_text", lambda w: related(ItemImage, "unique_item", ocr_text__icontains=w)),
    Source("file", ItemFile, "description", lambda w: related(ItemFile, "unique_item", description__icontains=w)),
]

LOCATION_SOURCES = [
    Source("name", Location, "name", lambda w: Q(name__icontains=w)),
    Source("purpose", Location, "purpose", lambda w: Q(purpose__icontains=w)),
    # Codes match whole, so that "R3" does not find R30 to R39.
    Source("code", Location, "short_name", lambda w: Q(short_name__iexact=w)),
    Source("code", Location, "unique_identifier", lambda w: Q(unique_identifier__iexact=w)),
    Source("code", Location, "locatable_identifier", lambda w: Q(locatable_identifier__iexact=w)),
    Source("description", Location, "physical_description", lambda w: Q(physical_description__icontains=w)),
]


def item_path(word):
    places = ItemLocation.objects.filter(item=OuterRef("pk"), location__descriptive_identifier__icontains=word,
                                         **ACTIVE_LOCATION)
    unique_items = UniqueItem.active.filter(item=OuterRef("pk"), location__descriptive_identifier__icontains=word)
    return Exists(places) | Exists(unique_items)


KINDS = [
    # kind, entries, sources, path of one word, name to sort by
    ("location", lambda: Location.active.all(), LOCATION_SOURCES,
     lambda w: Q(descriptive_identifier__icontains=w), Coalesce(NullIf("purpose", Value("")), "name")),
    ("item", lambda: Item.active.all(), ITEM_SOURCES, item_path, Coalesce("name", Value(""))),
    ("unique", lambda: UniqueItem.active.filter(item__is_deleted=False), UNIQUE_SOURCES,
     lambda w: Q(location__descriptive_identifier__icontains=w), F("item__name")),
]


def find(kind, queryset, sources, path, sort_name, words, limit):
    sources = [source for source in sources if searchable(source.model, source.field)]
    with_path = searchable(Location, "descriptive_identifier")

    def own(word):
        return any_of(source.match(word) for source in sources)

    for word in words:
        queryset = queryset.filter(own(word) | path(word) if with_path else own(word))
    queryset = queryset.filter(any_of(own(word) for word in words))

    def hit(keys):
        return Case(When(any_of(source.match(word) for source in sources if source.key in keys for word in words),
                         then=Value(True)), default=Value(False), output_field=BooleanField())

    keys = list(dict.fromkeys(source.key for source in sources))
    hits = {f"hit_{key}": hit({key}) for key in keys}
    named = hit(NAME_KEYS & set(keys))
    rows = (queryset.annotate(**hits, named=named, sort_name=Lower(sort_name))
            .order_by("-named", "sort_name", "pk").values("pk", "named", *hits)[:limit])
    return [Hit(kind, row["pk"], 2 if row["named"] else 1,
                tuple(key for key in keys if row[f"hit_{key}"] and key not in NAME_KEYS), rank)
            for rank, row in enumerate(rows)]


def search(words, limit):
    """The first `limit` hits of each kind in their order (hits on the name first, then by name), and whether
    any kind has more. The caller merges them, so a page of results never needs more of a kind than this."""
    hits, more = [], False
    for kind, entries, sources, path, sort_name in KINDS:
        found = find(kind, entries(), sources, path, sort_name, words, limit + 1)
        more |= len(found) > limit
        hits += found[:limit]
    return hits, more
