"""
The search in the database (icontains), for development and small installations without a search
service (docs/search.md). An entry is a hit when at least one word matches its own text (name, description,
category, photos, …), so that searching a room does not list everything stored in it. It ranks by how many words
match it, its own text or the path of where it is (the names of its location and of the locations above): the
best match first, those matching all words at the top. Its category's keywords count as well, but alone make a
hit only within a scope (a category, a location): in the search of everything the category is that hit.
"""
from dataclasses import dataclass
from functools import reduce
from operator import add, or_
from typing import Callable

from django.db.models import BooleanField, Case, CharField, Exists, F, IntegerField, OuterRef, Q, Value, When
from django.db.models.functions import Cast, Coalesce, Lower

from ..label_ids import core
from ..models import (Category, Item, ItemBarcode, ItemFile, ItemImage, ItemLocation, LabelId, Location,
                      LocationFormerCode, UniqueItem)
from .base import NAME_KEYS, Hit
from .fields import exported_rows, searchable


@dataclass(frozen=True)
class Source:
    key: str  # what a hit is shown as (render.SOURCE_LABELS); NAME_KEYS count as a hit on the name
    model: type  # the model and field holding the text, checked by fields.searchable
    field: str
    match: Callable[[str], Q]  # one word, on the searched queryset
    # False: a match only ranks the entry higher, unless searching within a scope (its category's keywords: alone
    # they would list hundreds of items in the search of everything, where the category itself is the hit).
    alone: bool = True
    # The text on the searched rows, comma-separated, whose matching parts the result names ("keywords: Spax").
    parts: str = ""


def related(model, owner, *conditions, **lookups):
    """Whether a related row the export keeps matches, e.g. a photo of the item."""
    return Exists(model.objects.filter(exported_rows(model), *conditions, **{owner: OuterRef("pk")}, **lookups))


def label(owner, word):
    """Whether its label ID (assigned) contains the word, from three symbols on ("K7R" finds K7R-4XD). Compared as
    text: LabelIdField itself only takes whole IDs."""
    part = core.normalize_part(word)
    if part is None or len(part) < 3:
        return Q(pk__in=[])
    codes = LabelId.objects.assigned().annotate(text=Cast("code", CharField())).filter(**{owner: OuterRef("pk")},
                                                                                      text__contains=part)
    return Exists(codes)


def code_start(field, word):
    """A code that starts with the word, or one of whose parts does (HW.R3 for R3). A single symbol only
    whole, so that "a" does not find every compartment a."""
    if len(word) < 2:
        return Q(**{f"{field}__iexact": word})
    return Q(**{f"{field}__istartswith": word}) | Q(**{f"{field}__icontains": f".{word}"})


def exact_code(word):
    """The location with exactly this code, first among those whose codes start with it."""
    return Q(unique_identifier__iexact=word) | Q(locatable_identifier__iexact=word) | Q(short_name__iexact=word)


def any_of(conditions):
    return reduce(or_, conditions)


GENERAL = Q(unique_item__isnull=True)  # photos and files of the item itself, not of one of its unique items
ACTIVE_LOCATION = {"location__is_deleted": False, "location__is_reserved": False}

ITEM_SOURCES = [
    Source("name", Item, "name", lambda w: Q(name__icontains=w)),
    Source("description", Item, "description", lambda w: Q(description__icontains=w)),
    Source("category", Category, "full_name", lambda w: Q(category__full_name__icontains=w)),
    Source("category_keywords", Category, "keywords", lambda w: Q(category__keywords__icontains=w),
           alone=False, parts="category__keywords"),
    Source("barcode", ItemBarcode, "data", lambda w: related(ItemBarcode, "item", data__icontains=w)),
    Source("photo", ItemImage, "description", lambda w: related(ItemImage, "item", GENERAL, description__icontains=w)),
    Source("photo_text", ItemImage, "ocr_text", lambda w: related(ItemImage, "item", GENERAL, ocr_text__icontains=w)),
    Source("file", ItemFile, "description", lambda w: related(ItemFile, "item", GENERAL, description__icontains=w)),
    Source("label", LabelId, "code", lambda w: label("item", w)),
]

UNIQUE_SOURCES = [
    Source("name", Item, "name", lambda w: Q(item__name__icontains=w)),
    Source("name", UniqueItem, "name", lambda w: Q(name__icontains=w)),
    Source("category", Category, "full_name", lambda w: Q(item__category__full_name__icontains=w)),
    Source("category_keywords", Category, "keywords", lambda w: Q(item__category__keywords__icontains=w),
           alone=False, parts="item__category__keywords"),
    Source("notes", UniqueItem, "notes", lambda w: Q(notes__icontains=w)),
    Source("photo", ItemImage, "description", lambda w: related(ItemImage, "unique_item", description__icontains=w)),
    Source("photo_text", ItemImage, "ocr_text", lambda w: related(ItemImage, "unique_item", ocr_text__icontains=w)),
    Source("file", ItemFile, "description", lambda w: related(ItemFile, "unique_item", description__icontains=w)),
    Source("label", LabelId, "code", lambda w: label("unique_item", w)),
]

LOCATION_SOURCES = [
    Source("name", Location, "name", lambda w: Q(name__icontains=w)),
    Source("purpose", Location, "purpose", lambda w: Q(purpose__icontains=w)),
    # Codes from their start or from a part (after a dot): R006 finds R006 and R006.a, R00 finds R001 to R009.
    Source("code", Location, "short_name", lambda w: Q(short_name__iexact=w)),
    Source("code", Location, "unique_identifier", lambda w: code_start("unique_identifier", w)),
    Source("code", Location, "locatable_identifier", lambda w: code_start("locatable_identifier", w)),
    # A code it had before still finds it (renamed or moved).
    Source("code", LocationFormerCode, "code", lambda w: related(LocationFormerCode, "location", code__iexact=w)),
    Source("description", Location, "description", lambda w: Q(description__icontains=w)),
    Source("label", LabelId, "code", lambda w: label("location", w)),
]


def item_path(word):
    places = ItemLocation.objects.filter(item=OuterRef("pk"), location__descriptive_identifier__icontains=word,
                                         **ACTIVE_LOCATION)
    unique_items = UniqueItem.active.filter(item=OuterRef("pk"), location__descriptive_identifier__icontains=word)
    return Exists(places) | Exists(unique_items)


KINDS = [
    # kind, entries, sources, path of one word, what to sort by, exact hit of one word (ranks first)
    ("location", lambda: Location.active.all(), LOCATION_SOURCES,
     lambda w: Q(descriptive_identifier__icontains=w), F("unique_identifier"), exact_code),  # by code, as in the tree
    ("item", lambda: Item.active.all(), ITEM_SOURCES, item_path, Coalesce("name", Value("")), None),
    ("unique", lambda: UniqueItem.active.filter(item__is_deleted=False), UNIQUE_SOURCES,
     lambda w: Q(location__descriptive_identifier__icontains=w), F("item__name"), None),
]


def find(kind, queryset, sources, path, sort_name, words, limit, exact=None, scoped=False):
    sources = [source for source in sources if searchable(source.model, source.field)]
    with_path = searchable(Location, "descriptive_identifier")

    def own(word, ranking=True):
        return any_of(source.match(word) for source in sources if ranking or source.alone or scoped)

    def counted(conditions):
        return reduce(add, (Case(When(condition, then=Value(1)), default=Value(0), output_field=IntegerField())
                            for condition in conditions))

    queryset = queryset.filter(any_of(own(word, ranking=False) for word in words))
    # How many of the words match it, itself or where it is: the best match first.
    matched = counted(own(word) | path(word) if with_path else own(word) for word in words)

    def hit(keys):
        return Case(When(any_of(source.match(word) for source in sources if source.key in keys for word in words),
                         then=Value(True)), default=Value(False), output_field=BooleanField())

    keys = list(dict.fromkeys(source.key for source in sources))
    hits = {f"hit_{key}": hit({key}) for key in keys}
    named = hit((NAME_KEYS | {"label"}) & set(keys))
    exactly = (Case(When(any_of(exact(word) for word in words), then=Value(True)), default=Value(False),
                    output_field=BooleanField()) if exact else Value(False, output_field=BooleanField()))
    parts = {source.key: source.parts for source in sources if source.parts}
    rows = (queryset.annotate(**hits, named=named, exactly=exactly, matched=matched, sort_name=Lower(sort_name))
            .order_by("-matched", "-exactly", "-named", "sort_name", "pk")
            .values("pk", "named", "exactly", "matched", *hits, *parts.values())[:limit])

    def snippets(row):
        """The matching parts of a text, e.g. the keywords of its category: the row does not show them."""
        found = {key: ", ".join(part.strip() for part in (row[text] or "").split(",")
                                if part.strip() and any(word.casefold() in part.casefold() for word in words))
                 for key, text in parts.items() if row[f"hit_{key}"]}
        return {key: text for key, text in found.items() if text}

    return [Hit(kind, row["pk"], 3 if row["exactly"] else 2 if row["named"] else 1,
                tuple(key for key in keys if row[f"hit_{key}"] and key not in NAME_KEYS), rank, snippets(row),
                matched=row["matched"])
            for rank, row in enumerate(rows)]


# Within one category (scope): its items and their unique items, no locations.
SCOPES = {"item": "category", "unique": "item__category"}


@dataclass(frozen=True)
class Below:
    """Within a location (a scope), at most `depth` levels below it (None: all; Location.in_tree): the locations
    below it, the items stored there and the unique items there."""
    location: Location
    depth: int = None

    def condition(self, kind):
        if kind == "location":
            return self.location.in_tree("", self.depth, itself=False)
        if kind == "item":
            return Exists(ItemLocation.objects.filter(self.location.in_tree("location", self.depth),
                                                      item=OuterRef("pk"), **ACTIVE_LOCATION))
        if kind == "unique":
            return self.location.in_tree("location", self.depth)
        return None


def within(scope, kind):
    """The condition for hits of this kind within the scope (a category or Below), None for kinds not in it."""
    if isinstance(scope, Below):
        return scope.condition(kind)
    return scope.in_tree(SCOPES[kind]) if kind in SCOPES else None


def search(words, limit, scope=None, kinds=None):
    """The first `limit` hits of each kind in their order (most words matched first, then hits on the name, then by
    name), and one more where a kind has more. The caller merges and counts them. With `scope` (a category or
    Below), only what is in it or below it; with `kinds`, only those."""
    hits = []
    for kind, entries, sources, path, sort_name, exact in KINDS:
        if kinds is not None and kind not in kinds:
            continue
        queryset = entries()
        if scope is not None:
            condition = within(scope, kind)
            if condition is None:
                continue
            queryset = queryset.filter(condition)
        hits += find(kind, queryset, sources, path, sort_name, words, limit + 1, exact, scoped=scope is not None)
    return hits
