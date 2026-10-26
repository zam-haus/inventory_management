from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.html import json_script
from django.utils.translation import gettext as _

from inventory.models import Location, UniqueItem

from .. import permissions
from ..levels import Tree
from ..models import BackgroundLayer, FloorPlan, LocationShape, UniqueItemPosition

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
    """Whether this location (by its type's map settings) or unique item is placed on the map at all."""
    if isinstance(obj, UniqueItem):
        return permissions.items_placeable()
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
        self.items = set(UniqueItemPosition.objects.values_list("unique_item_id", flat=True))
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


@register.simple_tag(takes_context=True)
def map_focus_url(context, obj):
    """The map of the level, showing (highlighted, its popup open: #p=…, map.js) a location, unique item or item
    (where it is first) or the place it is in, or "" if nothing of it is on the map: links to the map only where there
    is something to show."""
    index = _index(context)

    def link(shown, feature):
        number = index.tree.level_number(shown)
        return f"{reverse('maps:level', args=[number])}#p={feature}" if number is not None else ""

    if hasattr(obj, "places") and hasattr(obj, "obj"):  # a search result (inventory/search/render.py Entry)
        obj = obj.obj if isinstance(obj.obj, (Location, UniqueItem)) else [place.location.pk for place in obj.places]
    if isinstance(obj, Location):
        shown = index.shown_by(obj.pk)
        return link(shown, f"loc:{shown}") if shown else ""
    if isinstance(obj, UniqueItem):
        if obj.pk in index.items:
            return link(obj.location_id, f"item:{obj.pk}")
        shown = index.shown_by(obj.location_id) if obj.location_id else None
        return link(shown, f"loc:{shown}") if shown else ""
    for location_pk in obj:  # the places of an item
        shown = index.shown_by(location_pk)
        if shown:
            return link(shown, f"loc:{shown}")
    return ""


@register.simple_tag(takes_context=True)
def map_level_shown(context, number):
    """Whether the level has a plan or a position on it."""
    return number in _index(context).level_numbers()


@register.simple_tag(takes_context=True)
def map_dialog(context, obj):
    """What the "Position" button and dialog of a location or unique item offer: shown when there is something to show
    or the user may place it; editing for whoever may place it, else disabled with the reason (not for guests)."""
    user = context["request"].user
    if isinstance(obj, UniqueItem):
        denied = permissions.item_position_denied(user, obj)
        placeable = permissions.items_placeable()
    else:
        denied = permissions.shape_denied(user, obj)
        placeable = permissions.placeable(obj)
    focus_url = map_focus_url(context, obj)
    editable = placeable and not denied
    kinds = ["point"] if isinstance(obj, UniqueItem) else permissions.allowed_kinds(obj.type)
    return {"show": bool(focus_url or editable), "focus_url": focus_url, "editable": editable, "kinds": kinds,
            "area": "area" in kinds,
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
