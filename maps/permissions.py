"""What is placed on the map, and who may place it."""
from django.conf import settings
from django.utils.translation import gettext as _


def default_placed(kind):
    """Whether locations of a type without map settings are placed: levels, rooms, areas and storage units, but not
    containers, nor the parts of storage units (a type that is another type's sublocation type: compartments)."""
    from inventory.models import LocationType
    return (kind.category or "") in ("space", "storage_unit") and \
        not LocationType.objects.filter(sublocation_type=kind).exists()


# The shapes of locations of a type without map settings, by category.
DEFAULT_KINDS = {"space": ["area"], "storage_unit": ["point", "rectangle"], "container": ["point", "rectangle"]}


def allowed_kinds(kind):
    """The shapes ("point", "rectangle", "area") locations of the type can have on the map."""
    settings_ = getattr(kind, "map_settings", None)
    if settings_ is not None:
        return settings_.kinds()
    return list(DEFAULT_KINDS.get(kind.category or "", ["point"]))


def placeable(location):
    """Whether locations of this type are placed on the map (admin: the location type's map settings)."""
    settings_ = getattr(location.type, "map_settings", None)
    return settings_.placeable if settings_ is not None else default_placed(location.type)


def items_placeable():
    return settings.MAPS_PLACE_UNIQUE_ITEMS


def map_editor(user):
    """Whether the user may edit and move everything on the map (its edit mode): all staff, and whoever has
    maps.edit_map."""
    return user.is_active and (user.is_staff or user.has_perm("maps.edit_map"))


def edit_map_denied(user):
    if not map_editor(user):
        return _("Editing the map needs the permission to edit the map (all staff have it).")
    return None


def shape_denied(user, location):
    """Why `user` may not place `location` on the map, or None. Levels, rooms and areas (admin-only types) need
    maps.change_building_shape; everything else what moving it needs."""
    if not placeable(location):
        return _("Locations of type “%(type)s” are not placed on the map; they are where the location they are in "
                 "is.") % {"type": location.type}
    if map_editor(user):
        return None
    if location.type.admin_only:
        if not user.has_perm("maps.change_building_shape"):
            return _("Drawing levels, rooms and areas needs the permission to change building shapes.")
        return None
    if not user.has_perm("inventory.change_location"):
        return _("You do not have permission to change this location.")
    return None


def item_position_denied(user, unique_item):
    if not items_placeable():
        return _("Unique items are not placed on the map.")
    if unique_item.location_id is not None and map_editor(user):
        return None
    if not user.has_perm("inventory.change_uniqueitem"):
        return _("You do not have permission to change this unique item.")
    if unique_item.location_id is None:
        return _("Removed from the inventory.")
    return None


def plans_denied(user):
    """The floor plan pages (/map/plans/): maps.manage_floorplans, which only superusers have until it is given."""
    if not user.has_perm("maps.manage_floorplans"):
        return _("Floor plans need the permission to change floor plans.")
    return None
