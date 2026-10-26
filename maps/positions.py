"""Setting and clearing positions, with what moves along and the change log.

When something moves on the map, what is on or in it moves along (the boxes on a pallet). When it gets
another parent without a new position, its position and those of the things on or in it are cleared, so they
show the area of the new parent until someone places them. Building parts are left alone when they get another
parent: that is restructuring, and their areas stay where the building is.
"""
from django.contrib.gis.geos import GEOSException, GEOSGeometry
from django.db import transaction
from django.utils import formats
from django.utils.translation import gettext as _

from inventory import change_log
from inventory.models import ChangeLog

from . import geo, permissions
from .levels import Tree
from .models import LocationShape, UniqueItemPosition

FIELD = "map_position"


class PlacementError(ValueError):
    pass


def describe(shape):
    """The position as people read it in the change log ("" for none)."""
    if shape is None or shape.geometry is None:
        return ""
    if shape.kind == LocationShape.Kind.AREA:
        return _("area of %(area)s m²") % {"area": formats.number_format(geo.area_m2(shape.geometry), 1)}
    lon, lat = geo.anchor(shape.geometry).coords
    where = f"{lat:.6f}, {lon:.6f}"
    if shape.kind == LocationShape.Kind.RECTANGLE:
        size = shape.size_cm()
        return _("rectangle %(width)s × %(depth)s cm, turned %(rotation)s°, at %(where)s") % {
            "width": size[0] if size else "?", "depth": size[1] if size else "?",
            "rotation": formats.number_format(shape.rotation % 360, 0), "where": where}
    return _("point at %(where)s") % {"where": where}


def describe_point(point):
    if point is None:
        return ""
    return _("point at %(where)s") % {"where": f"{point.y:.6f}, {point.x:.6f}"}


def _log(subject, before, after, *, entry=None, **links):
    """The change in the entry of the same save (e.g. the move), else in an entry of its own."""
    if before == after:
        return
    change = {"field": FIELD, "before": before, "after": after, "internal": False}
    if entry is not None:
        entry.changes = [*entry.changes, change]
        entry.save(update_fields=["changes"])
    else:
        change_log.record(ChangeLog.Action.CHANGED, subject, changes=[change], **links)


def _item_links(unique_item):
    return {"unique_item": unique_item, "location": unique_item.location}


def parse_geometry(value, kinds=("Point", "Polygon")):
    """A WGS84 geometry from GeoJSON (or WKT) text, or PlacementError."""
    try:
        geometry = GEOSGeometry(value, srid=geo.WGS84) if isinstance(value, str) else value
    except (GEOSException, ValueError, TypeError) as error:
        raise PlacementError(_("The position could not be read.")) from error
    if geometry.srid not in (None, geo.WGS84):
        geometry = geo.wgs84(geometry)
    geometry.srid = geo.WGS84
    if geometry.geom_type not in kinds or geometry.empty or not geometry.valid:
        raise PlacementError(_("The position is not a valid %(kinds)s.") % {"kinds": " / ".join(kinds)})
    xs, ys = zip(*((geometry.coords,) if geometry.geom_type == "Point" else geometry.shell.coords))
    if not all(-180 <= x <= 180 for x in xs) or not all(-90 <= y <= 90 for y in ys):
        raise PlacementError(_("The position is outside the earth's coordinates."))
    return geometry


def shaped(location, kind, geometry, rotation=0.0, shape=None):
    """(kind, geometry, rotation) to store: a rectangle is given by its centre and becomes the polygon of the
    location's size; without a known size it stays a point."""
    if geometry is None:  # removed: the kind stays what it was (the column needs one)
        return kind or (shape.kind if shape else None) or LocationShape.Kind.POINT, None, 0.0
    if kind == LocationShape.Kind.AREA:
        return kind, parse_geometry(geometry, ("Polygon",)), 0.0
    point = parse_geometry(geometry, ("Point", "Polygon"))
    if point.geom_type == "Polygon":
        point = geo.anchor(point)
    shape = shape or LocationShape(location=location)
    size = shape.size_cm()
    if kind == LocationShape.Kind.RECTANGLE or (kind is None and size):
        if size:
            return LocationShape.Kind.RECTANGLE, geo.rectangle(point, size[0] / 100, size[1] / 100, rotation), \
                float(rotation) % 360
    return LocationShape.Kind.POINT, point, 0.0


def _carry(location_pks, item_location_pks, start, end, turn):
    """Moves the positions of the given locations and of the unique items at the given locations along."""
    for shape in LocationShape.objects.select_for_update().filter(location__in=location_pks,
                                                                  geometry__isnull=False):
        if shape.kind == LocationShape.Kind.AREA:
            continue
        before = describe(shape)
        shape.geometry = geo.moved(shape.geometry, start, end, turn)
        shape.rotation = (shape.rotation + turn) % 360 if shape.kind == LocationShape.Kind.RECTANGLE else 0.0
        shape.save(update_fields=["geometry", "rotation"])
        _log(shape.location, before, describe(shape), location=shape.location)
    for position in UniqueItemPosition.objects.select_for_update().select_related("unique_item").filter(
            unique_item__location__in=item_location_pks):
        before = describe_point(position.point)
        position.point = geo.moved(position.point, start, end, turn)
        position.save(update_fields=["point"])
        _log(position.unique_item, before, describe_point(position.point), **_item_links(position.unique_item))


@transaction.atomic
def set_location_shape(location, kind, geometry, rotation=0.0, *, size=None, entry=None):
    """Places the location (geometry None: removes its position); `size` (width, depth) in cm is its own, e.g. from
    the dialog. What is on or in it moves along when it had a position before and gets a new one."""
    allowed = permissions.allowed_kinds(location.type)
    if geometry is not None:
        if kind is None and allowed == [LocationShape.Kind.AREA]:
            kind = LocationShape.Kind.AREA
        elif kind == LocationShape.Kind.RECTANGLE and kind not in allowed and LocationShape.Kind.POINT in allowed:
            kind = LocationShape.Kind.POINT
        elif kind is None and LocationShape.Kind.RECTANGLE not in allowed:
            kind = LocationShape.Kind.POINT
        if kind is not None and kind not in allowed:
            raise PlacementError(_("Locations of type “%(type)s” are not placed as %(kind)s.") % {
                "type": location.type, "kind": LocationShape.Kind(kind).label})
    shape, _created = LocationShape.objects.select_for_update().get_or_create(location=location)
    if size:
        # The type's usual size is not kept as its own: a changed size of the type then applies here, too.
        settings_ = getattr(location.type, "map_settings", None)
        usual = (settings_.default_width_cm, settings_.default_depth_cm) if settings_ else None
        shape.width_cm, shape.depth_cm = (None, None) if tuple(size) == usual else size
    kind, geometry, rotation = shaped(location, kind, geometry, rotation, shape)
    before, old = describe(shape), shape.geometry
    old_rotation = shape.rotation
    shape.kind, shape.geometry, shape.rotation = kind, geometry, rotation
    shape.save()
    _log(location, before, describe(shape), entry=entry, location=location)
    if old is not None and geometry is not None and kind != LocationShape.Kind.AREA:
        below = Tree().descendants(location.pk)
        turn = rotation - old_rotation if kind == LocationShape.Kind.RECTANGLE else 0.0
        _carry(below, [location.pk, *below], geo.anchor(old), geo.anchor(geometry), turn)
    return shape


@transaction.atomic
def clear_moved(location, *, entry=None):
    """Clears the positions of a location that got another parent, and of what is on or in it."""
    if location.type.category == "space":
        return
    pks = [location.pk, *Tree().descendants(location.pk)]
    for shape in LocationShape.objects.select_for_update().select_related("location").filter(
            location__in=pks, geometry__isnull=False).exclude(kind=LocationShape.Kind.AREA):
        before = describe(shape)
        shape.geometry, shape.rotation = None, 0.0
        shape.save(update_fields=["geometry", "rotation"])
        own = shape.location_id == location.pk
        _log(location if own else shape.location, before, "", entry=entry if own else None,
             location=location if own else shape.location)
    for position in UniqueItemPosition.objects.select_related("unique_item").filter(unique_item__location__in=pks):
        _log(position.unique_item, describe_point(position.point), "", **_item_links(position.unique_item))
        position.delete()


@transaction.atomic
def set_item_position(unique_item, point):
    """Places the unique item at a point (None: removes its own position; it then shows its location's)."""
    position = UniqueItemPosition.objects.select_for_update().filter(unique_item=unique_item).first()
    before = describe_point(position.point if position else None)
    if point is None:
        if position:
            position.delete()
    else:
        point = parse_geometry(point, ("Point",))
        if position:
            position.point = point
            position.save(update_fields=["point"])
        else:
            UniqueItemPosition.objects.create(unique_item=unique_item, point=point)
    _log(unique_item, before, describe_point(point), **_item_links(unique_item))


def size_from(context, prefix="map_"):
    """(width, depth) in cm a dialog sent (map_width_cm, map_depth_cm), None if not both, or PlacementError."""
    values = [(context.get(f"{prefix}{name}_cm") or "").strip() for name in ("width", "depth")]
    if not all(values):
        return None
    try:
        width, depth = (round(float(value.replace(",", "."))) for value in values)
    except ValueError as error:
        raise PlacementError(_("Width and depth are numbers of centimetres.")) from error
    if not (0 < width <= 100000 and 0 < depth <= 100000):
        raise PlacementError(_("Width and depth are numbers of centimetres."))
    return width, depth


def placement_from(context, prefix="map_"):
    """{kind, geometry, rotation, size} a dialog sent along (map_kind, map_geometry, map_rotation, map_width_cm,
    map_depth_cm), else None."""
    value = (context.get(f"{prefix}geometry") or "").strip()
    if not value:
        return None
    try:
        rotation = float(context.get(f"{prefix}rotation") or 0)
    except ValueError:
        rotation = 0.0
    kind = context.get(f"{prefix}kind") or None
    if kind not in (None, *LocationShape.Kind.values):
        kind = None
    return {"kind": kind, "geometry": value, "rotation": rotation, "size": size_from(context, prefix)}


def item_point(unique_item):
    position = UniqueItemPosition.objects.filter(unique_item=unique_item).first()
    return position.point if position else None


def location_moved(sender, instance, old_parent, context, **kwargs):
    entry = instance.__dict__.pop("_change_log_entry", None)
    try:
        placement = placement_from(context)
    except PlacementError:
        placement = None
    if placement is not None and instance.type.category != "space" and permissions.placeable(instance):
        try:
            set_location_shape(instance, placement["kind"], placement["geometry"], placement["rotation"],
                               size=placement["size"], entry=entry)
            return
        except PlacementError:
            pass  # moved all the same; the position is cleared like without one
    clear_moved(instance, entry=entry)


def unique_item_moved(sender, instance, old_parent, context, **kwargs):
    value = (context.get("map_point") or "").strip()
    point = None
    if value and instance.location_id is not None and permissions.items_placeable():
        try:
            point = parse_geometry(value, ("Point",))
        except PlacementError:
            point = None
    if point is not None or item_point(instance) is not None:
        set_item_position(instance, point)

