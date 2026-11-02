from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.html import json_script
from django.utils.translation import gettext as _

from inventory.change_log import stamp
from inventory.models import Location, UniqueItem

from .. import permissions
from ..levels import Tree
from ..models import BackgroundLayer, FloorPlan, LocationShape, UniqueItemPosition
from ..positions import last_set

register = template.Library()


@register.simple_tag(takes_context=True)
def map_shape_denied(context, location):
    """Why the current user may not place `location` on the map ("" if they may)."""
    return permissions.shape_denied(context["request"].user, location) or ""


@register.simple_tag(takes_context=True)
def map_item_denied(context, unique_item):
    return permissions.item_position_denied(context["request"].user, unique_item) or ""


@register.filter
def map_placeable(obj):
    """Whether this location (by its type's map settings) or unique item (always) is placed on the map at all."""
    if isinstance(obj, UniqueItem):
        return True
    return permissions.placeable(obj)


@register.simple_tag
def map_config():
    """The background layers (admin: Background layers) and start view for the map scripts (map.js), as
    <script id="map-config">."""
    layers = [{"name": layer.name, "url": layer.url, "attribution": layer.attribution, "max_zoom": layer.max_zoom,
               "default": layer.is_default} for layer in BackgroundLayer.objects.filter(active=True)]
    return json_script({"layers": layers, "start": settings.MAPS_START, "none": _("No background")}, "map-config")


class _Index:
    """What is on the map, loaded once per request: the location tree and the locations with a position."""

    def __init__(self):
        self.tree = Tree()
        self.shaped = set(LocationShape.objects.filter(geometry__isnull=False).values_list("location_id", flat=True))
        self.items = set(UniqueItemPosition.objects.filter(geometry__isnull=False)
                         .values_list("unique_item_id", flat=True))
        self.plan_levels = set(FloorPlan.objects.filter(active=True, corners__isnull=False)
                               .values_list("level", flat=True))

    def located(self, pk):
        """Whether the location or one above it has a position."""
        return self.shown_by(pk) is not None

    def shown_by(self, pk):
        """The location shown for it on the map: itself, else the nearest one above it with a position."""
        return next((node for node in self.tree.chain(pk) if node in self.shaped), None)

    def level_numbers(self):
        numbers = set(self.plan_levels)
        self.tree.load(LocationShape.objects.filter(geometry__isnull=False).values("location_id"))
        for pk in self.shaped:
            number = self.tree.level_number(pk)
            if number is not None:
                numbers.add(number)
        return numbers


def _index(context):
    request = context.get("request")
    holder = request if request is not None else context
    index = getattr(holder, "_maps_index", None)
    if index is None:
        index = _Index()
        try:
            holder._maps_index = index
        except AttributeError:
            pass
    return index


def _focus(index, obj):
    """What the map shows for a location, unique item or item (where it is first): (level number, feature id,
    location shown for it, or None for a unique item's own position), or None if nothing of it is on the map."""

    def found(shown, feature, location):
        number = index.tree.level_number(shown)
        return (number, feature, location) if number is not None else None

    if hasattr(obj, "places") and hasattr(obj, "obj"):  # a result row (inventory/search/render.py Entry)
        obj = obj.obj if isinstance(obj.obj, (Location, UniqueItem)) else [place.location.pk for place in obj.places]
    if isinstance(obj, Location):
        shown = index.shown_by(obj.pk)
        return found(shown, f"loc:{shown}", shown) if shown else None
    if isinstance(obj, UniqueItem):
        if obj.pk in index.items:
            return found(obj.location_id, f"item:{obj.pk}", None)
        shown = index.shown_by(obj.location_id) if obj.location_id else None
        return found(shown, f"loc:{shown}", shown) if shown else None
    for location_pk in obj:  # the places of an item
        shown = index.shown_by(location_pk)
        if shown:
            return found(shown, f"loc:{shown}", shown)
    return None


@register.simple_tag(takes_context=True)
def map_focus_url(context, obj):
    """The map of the level, showing (highlighted, its popup open: ?p=…, map.js) a location, unique item or item
    (where it is first) or the place it is in, or "" if nothing of it is on the map: links to the map only where there
    is something to show."""
    focus = _focus(_index(context), obj)
    return f"{reverse('maps:level', args=[focus[0]])}?p={focus[1]}" if focus else ""


@register.simple_tag(takes_context=True)
def map_preload(context, entries):
    """Loads where the locations of these result rows are in the tree at once, and what their maps show (map_slides),
    so that the rows need no query each. Renders the map scripts' settings once if a row has a map, else nothing."""
    pks = []
    for entry in entries:
        if isinstance(entry.obj, Location):
            pks.append(entry.obj.pk)
        elif isinstance(entry.obj, UniqueItem):
            pks.append(entry.obj.location_id)
        pks += [place.location.pk for place in entry.places]
    if not pks:
        for entry in entries:
            entry.map_slides = []
        return ""
    index = _index(context)
    index.tree.load(pks)
    _slides(index, entries, context["request"].user)
    # Before map.js reads them (map_mini.js loads it once a row's map is shown); once per page.
    if any(entry.map_slides for entry in entries) and not getattr(index, "config_shown", False):
        index.config_shown = True
        return map_config()
    return ""


def _slides(index, entries, user):
    """The maps of result rows after their photos (slots/result_slides.html), as entry.map_slides: one per level, with
    all of the row there highlighted (a unique item or location, else the places of an item). Each slide: data_url
    and focus (feature ids, comma separated) for map_mini.js, url (the large map showing the same) and marks, one per
    thing shown: {target, around (the location highlighted instead, without a position of its own), stamp (when the
    position highlighted was set, inventory.change_log.stamp)}. A few queries for all rows."""
    for entry in entries:
        targets = [entry.obj] if isinstance(entry.obj, (Location, UniqueItem)) else \
            [place.location for place in entry.places]
        slides = {}
        for target in targets:
            focus = _focus(index, target)
            if focus is None:
                continue
            number, feature, shown = focus
            slide = slides.setdefault(number, {"number": number, "features": [], "marks": []})
            if feature not in slide["features"]:
                slide["features"].append(feature)
            exact = shown is None or (isinstance(target, Location) and shown == target.pk)
            slide["marks"].append({"target": target, "feature": feature, "around": None if exact else shown})
        entry.map_slides = list(slides.values())
    marks = [mark for entry in entries for slide in entry.map_slides for mark in slide["marks"]]
    if not marks:
        return
    around = Location.objects.select_related("type").in_bulk({mark["around"] for mark in marks if mark["around"]})
    set_at = last_set({mark["feature"] for mark in marks})
    for mark in marks:
        mark["around"] = around.get(mark["around"])
        mark["stamp"] = stamp(set_at.get(mark["feature"]), user)
    for entry in entries:
        for slide in entry.map_slides:
            slide["focus"] = ",".join(slide["features"])
            slide["data_url"] = reverse("maps:level_data", args=[slide["number"]])
            slide["url"] = f"{reverse('maps:level', args=[slide['number']])}?p={slide['focus']}"


@register.simple_tag(takes_context=True)
def map_slides(context, entry):
    """The maps a result row shows after its photos (see _slides; loaded for the list by map_preload)."""
    if not hasattr(entry, "map_slides"):
        _index(context).tree.load([entry.obj.pk] if isinstance(entry.obj, Location) else
                                  [entry.obj.location_id] if isinstance(entry.obj, UniqueItem) else
                                  [place.location.pk for place in entry.places])
        _slides(_index(context), [entry], context["request"].user)
    return entry.map_slides


@register.simple_tag(takes_context=True)
def map_level_shown(context, number):
    """Whether the level has a plan or a position on it."""
    return number in _index(context).level_numbers()


@register.simple_tag(takes_context=True)
def map_place(context, obj):
    """What the position in the grey box of a location or unique item offers (place_inline.html): shown when there
    is something to show or the user may place it; the map when it or the place it is in has a position (has_own: its
    own); editing for whoever may place it, else disabled with the reason (not for guests); another level for whoever
    may also move it (move_url)."""
    user = context["request"].user
    index = _index(context)
    if isinstance(obj, UniqueItem):
        denied = permissions.item_position_denied(user, obj)
        placeable = True
        has_own = obj.pk in index.items
        move_url = reverse("move_unique_item", args=[obj.pk]) if user.has_perm("inventory.change_uniqueitem") else ""
    else:
        denied = permissions.shape_denied(user, obj)
        placeable = permissions.placeable(obj)
        has_own = obj.pk in index.shaped
        move_url = reverse("location_move", args=[obj.pk]) \
            if obj.type.moveable and user.has_perm("inventory.change_location") else ""
    focus = _focus(index, obj)
    focus_url = map_focus_url(context, obj)
    # Without its own position: the location shown instead ("it is in …", highlighted).
    around = Location.objects.filter(pk=focus[2]).first() if focus and not has_own and focus[2] else None
    # When the position highlighted was set, and by whom as in the change log.
    set_at = last_set([focus[1]]).get(focus[1]) if focus else None
    editable = placeable and not denied
    # Unique items: every shape (their item only gives the usual one).
    kinds = list(UniqueItemPosition.Kind.values) if isinstance(obj, UniqueItem) else \
        permissions.allowed_kinds(obj.type)
    return {"show": bool(focus_url or editable), "focus_url": focus_url, "has_map": bool(focus_url),
            # The map as on the large one with ?p= (map.js focus): the level and what it shows.
            "data_url": reverse("maps:level_data", args=[focus[0]]) if focus else "", "focus": focus[1] if focus else "",
            "around": around, "stamp": stamp(set_at, user),
            "has_own": has_own, "editable": editable, "kinds": kinds, "area": "area" in kinds,
            "move_url": move_url if editable else "",
            "edit_denied": denied if placeable and denied and user.is_authenticated else ""}


@register.simple_tag(takes_context=True)
def map_mini(context, location):
    """What the small map in the location window needs: the level's data and what to highlight (the location, else
    the nearest one above it with a position), or None if nothing of it is on the map."""
    from ..levels import effective_shape
    index = _index(context)
    if not index.located(location.pk):
        return None
    found = effective_shape(location)
    number = index.tree.level_number(location.pk)
    if found is None or number is None:
        return None
    _shape, source, exact = found
    return {"data_url": reverse("maps:level_data", args=[number]), "focus": f"loc:{source.pk}", "exact": exact,
            "source": source}
