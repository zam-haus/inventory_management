"""Locations from what someone typed or scanned into a location field, via the one reader of codes
(inventory/codes.py)."""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import codes
from .codes import locations_by_code, reserved_by_code, scan_prefixes
from .models import Location

__all__ = ["NotActivated", "location_by_code", "location_from_found", "location_from_label_id",
           "location_from_reference", "locations_by_code", "reserved_by_code", "resolve_location_reference",
           "scan_prefixes"]


class NotActivated(ValidationError):
    """The reference names a reserved container; `location` is it, to offer activating it."""

    def __init__(self, location):
        super().__init__(_("%(code)s is not activated yet: scan its label or open it to say where it is.")
                         % {"code": location.unique_identifier})
        self.location = location


def location_by_code(code):
    """The one location with this code (see locations_by_code); raises Location.DoesNotExist or
    Location.MultipleObjectsReturned."""
    found = locations_by_code(code)
    if len(found) > 1:
        raise Location.MultipleObjectsReturned
    if not found:
        raise Location.DoesNotExist
    return found[0]


def location_from_found(found):
    """The location a reading (codes.Found) names: directly, or by the location's label ID; else None."""
    if found.kind == codes.LOCATION:
        return found.location
    return codes.label_id_location(found)


def location_from_label_id(value):
    """The location an assigned label ID (typed, or the URL in its QR code) belongs to, or None."""
    found = codes.resolve_code(value)
    return codes.label_id_location(found)


def location_from_reference(value):
    """The location a code, label ID, label URL or location URL names, or None (no primary keys: in searches a
    number is text)."""
    return location_from_found(codes.resolve_code(value))


def resolve_location_reference(value):
    """The location a code, label ID, label URL, location URL or primary key names, also when scanned with a
    wrong keyboard layout; else ValidationError (NotActivated for a reserved container)."""
    found = codes.resolve_code(value, numbers_are_pks=True)
    if (location := location_from_found(found)) is not None:
        return location
    if found.kind == codes.RESERVED:
        raise NotActivated(found.location)
    if found.kind == codes.AMBIGUOUS:
        raise ValidationError(found.reason)
    if found.kind == codes.LABEL_ID:
        raise ValidationError(_("%(code)s does not belong to a location.") % {"code": found.lid.display})
    raise ValidationError(_("Location not found."))
