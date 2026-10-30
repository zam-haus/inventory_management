"""The help page for users (/help/): items, locations, unique items, location types and codes.

The prose is one template per language (inventory/help/help_<lang>.html, German as fallback); the location types,
the rules derived from their flags and where each type usually stands come from the database, so the page follows
the configuration.
"""
from collections import Counter, defaultdict

from django.db.models import Count, OuterRef, Subquery
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import get_language, gettext as _
from django.views.generic.base import TemplateView

from .icons import icon
from .location_display import CATEGORY_ICONS
from .models import Location, LocationType

# Sections the contextual links point to ({% help_link %}); renaming one breaks those links.
ANCHORS = ("ueberblick", "sachen", "zamid", "baum", "typen", "regeln", "codes")

def help_link(anchor, text=None):
    """A quiet "More about this" link to one section of the help page ({% help_link %})."""
    if anchor not in ANCHORS:
        raise ValueError(f"Unknown help section {anchor!r}: one of {', '.join(ANCHORS)}.")
    return format_html('<a class="help-link" href="{}#{}">{}{}</a>', reverse("help"), anchor,
                       icon("question-circle"), text or _("More about this"))


# How many parent types a card names under "usually stands in".
PARENTS_SHOWN = 4


def _names(types):
    """'A', 'A and B', 'A, B and C'."""
    names = [t.name for t in types]
    if len(names) < 2:
        return "".join(names)
    return _("%(first)s and %(last)s") % {"first": ", ".join(names[:-1]), "last": names[-1]}


def code_pattern(location_type):
    """How the code of a location of this type is built, e.g. 'K + 4 digits'."""
    letters = location_type.auto_sequence == LocationType.Sequence.LOWERCASE
    if not location_type.unique:
        return _("Code above + dot + letter a–z") if letters else _("Code above + dot + number")
    if location_type.auto_short_name_prefix:
        return _("%(prefix)s + %(count)s digits") % {
            "prefix": location_type.auto_short_name_prefix, "count": location_type.auto_short_name_padding_length}
    return _("Own code")


def facts(location_type):
    """(state, text) pairs for a type card; state is "yes", "no" or "lock" (admin only)."""
    out = [
        ("yes", _("Moves with its contents")) if location_type.moveable else ("no", _("Stays where it is")),
        ("no", _("Holds only items, no locations")) if location_type.no_sublocations
        else ("yes", _("Holds further locations")),
    ]
    if location_type.sublocation_type_id:
        out.append(("yes", _("Divided into %(type)s") % {"type": location_type.sublocation_type.name}))
    if location_type.area_numbering:
        out.append(("yes", _("Number from the number range of the room")))
    if location_type.admin_only:
        out.append(("lock", _("Changed in the admin only")))
    elif location_type.deletable_in_frontend:
        out.append(("yes", _("Can be deleted here when empty")))
    else:
        out.append(("no", _("Deleted in the admin only")))
    return out


def _category_texts():
    return {
        LocationType.Category.SPACE: _("Part of the building, never moves. Created in the admin only; what is in it "
                                       "can be moved freely."),
        LocationType.Category.STORAGE_UNIT: _(
            "Furniture for storing things, with its compartments and drawers. A storage unit stays a storage unit, "
            "even on wheels. Shelves and cabinets are usually numbered from left to right in the room. "
            "Compartments and drawers always count from the bottom up: a is the lowest."),
        LocationType.Category.CONTAINER: _("Moves through the building with its contents."),
        "": _("Not part of the building structure."),
    }


def type_groups(types, parents):
    """Type cards grouped by category (spaces, storage units, containers, then those without one).

    Facts every type of a group shares are said once for the group, not on each card."""
    texts = _category_texts()
    by_category = defaultdict(list)
    for location_type in types:
        by_category[location_type.category].append(location_type)
    groups = []
    for category in [*LocationType.Category.values, ""]:
        members = by_category.get(category)
        if not members:
            continue
        lists = [facts(t) for t in members]
        common = [fact for fact in lists[0] if all(fact in other for other in lists[1:])] if len(members) > 1 else []
        cards = []
        for location_type, fact_list in zip(members, lists):
            above = parents.get(location_type.pk, [])
            if above:
                where = _("Usually stands in: %(types)s") % {"types": ", ".join(above[:PARENTS_SHOWN])}
            elif not location_type.unique:
                where = ""
            elif location_type.structure == LocationType.Structure.LEVEL:
                where = _("Top level")
            else:
                where = _("Top level, on its own")
            cards.append({
                "type": location_type,
                "pattern": code_pattern(location_type),
                "facts": [fact for fact in fact_list if fact not in common],
                "where": where,
            })
        groups.append({
            "category": category or "none",
            "icon": CATEGORY_ICONS.get(category, "geo-alt"),
            "title": LocationType.CATEGORY_PLURALS.get(category, _("Without category")),
            "text": texts[category],
            "cards": cards,
            "common": common,
        })
    return groups


def parent_types():
    """Type pk → names of the types its active locations stand in, most frequent first."""
    pairs = (Location.active.filter(parent_location__isnull=False)
             .values("type", "parent_location__type__name").annotate(n=Count("pk")))
    counts = defaultdict(Counter)
    for pair in pairs:
        counts[pair["type"]][pair["parent_location__type__name"]] += pair["n"]
    return {pk: [name for name, _n in sorted(c.items(), key=lambda item: (-item[1], item[0]))]
            for pk, c in counts.items()}


def rules(types):
    """What may stand in what, as sentences derived from the type flags; empty ones are left out."""
    leaf = [t for t in types if t.no_sublocations]
    numbered = [t for t in types if t.area_numbering]
    holders = [t for t in types if t.category == LocationType.Category.CONTAINER and not t.no_sublocations]
    derived = [t for t in types if not t.unique]
    moving = [t for t in types if t.moveable]
    admin = [t for t in types if t.admin_only]
    out = []
    if leaf:
        out.append(("box-arrow-in-down", _("%(types)s hold only items, no further locations.") % {
            "types": _names(leaf)}))
    if numbered:
        if holders:
            text = _("%(types)s stand in a space (level, room, area) or on %(holders)s, never in a compartment or "
                     "another shelf.") % {"types": _names(numbered), "holders": _names(holders)}
        else:
            text = _("%(types)s stand in a space (level, room, area), never in a compartment or another "
                     "shelf.") % {"types": _names(numbered)}
        out.append(("bookshelf", text))
    if derived:
        out.append(("grid-3x3", _("%(types)s exist only as part of another location. Their code builds on "
                                  "its code.") % {"types": _names(derived)}))
    if moving:
        out.append(("arrows-move", _("%(types)s move with everything in them. Their code stays the same.") % {
            "types": _names(moving)}))
    if admin:
        out.append(("shield-exclamation", _("%(types)s are created and changed by the admin team only. What is in "
                                            "them can be moved by anyone with permission.") % {"types": _names(admin)}))
    out.append(("trash3", _("A location can only be deleted when it is empty: no items, no unique items, no "
                            "locations in it.")))
    return out


def help_context():
    example = Location.active.filter(type=OuterRef("pk")).order_by("locatable_identifier").values(
        "unique_identifier")[:1]
    types = list(LocationType.objects.select_related("sublocation_type")
                 .annotate(example=Subquery(example)).order_by("name"))
    # Order within a group: own codes before parts of something, then from the outside in (level, room, area).
    structure_order = {value: index for index, value in enumerate(LocationType.Structure.values)}
    types.sort(key=lambda t: (not t.unique, structure_order.get(t.structure, len(structure_order)), t.name))
    return {"type_groups": type_groups(types, parent_types()), "rules": rules(types)}


class HelpView(TemplateView):
    def get_template_names(self):
        return [f"inventory/help/help_{(get_language() or 'de')[:2]}.html", "inventory/help/help_de.html"]

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **help_context()}
