from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import Resolver404, resolve
from django.utils.translation import gettext_lazy as _

from .keyboard_layouts import layout_corrections
from .label_ids import core as label_id_core, parsing as label_id_parsing
from .models import LabelId, Location


def scan_prefixes():
    """Location labels start with DEFAULT_DOMAIN, old ones with an earlier domain (DOMAIN_ALIASES)."""
    return [url.rstrip("/") + "/" for url in (settings.DEFAULT_DOMAIN, *getattr(settings, "DOMAIN_ALIASES", ()))]


def location_from_label_id(value):
    """The location an assigned label ID (typed, or the URL in its QR code) belongs to, or None."""
    try:
        code = label_id_parsing.code_from_scan(value)
    except label_id_core.InvalidLabelId:
        return None
    lid = LabelId.objects.select_related("location").filter(pk=code).first()
    if lid is not None and lid.status == LabelId.Status.ASSIGNED and lid.location and not lid.location.is_deleted:
        return lid.location
    return None


def location_from_reference(value):
    """The location a scanned or pasted label ID or location label URL names, or None."""
    location = location_from_label_id(value)
    if location is None and "/" in value:
        try:
            location = resolve_location_reference(value)
        except ValidationError:
            pass
    return location


def resolve_location_reference(value):
    """Resolve identifiers or a detail URL, also when scanned with a wrong keyboard layout."""
    try:
        return _resolve(value)
    except ValidationError as error:
        # Label URLs start with a known domain; a garbled start reveals which
        # scanner and host layouts were mixed up.
        locations = set()
        corrections = {corrected for prefix in scan_prefixes() for corrected in layout_corrections(value, prefix)}
        for corrected in corrections:
            try:
                locations.add(_resolve(corrected))
            except ValidationError:
                pass
        if len(locations) > 1:
            raise ValidationError(_("Ambiguous scan; check the keyboard layout of the scanner."))
        if locations:
            return locations.pop()
        raise error


def _resolve(value):
    """Resolve identifiers or a detail URL, whose primary key wins over its slug."""
    try:
        if "/" in value:
            url = urlsplit(value)
            if url.scheme and url.scheme not in ("http", "https"):
                raise ValueError
            match = resolve(unquote(url.path))
            if match.url_name not in ("view_location", "view_location2"):
                raise ValueError
            pk = Location._meta.pk.clean(match.kwargs["pk"], None)
            return Location.active.get(pk=pk)

        matches = Location.active.filter(
            Q(unique_identifier=value) | Q(locatable_identifier=value)
        )
        # A numeric label is an identifier first, a database ID only as fallback.
        if matches.exists():
            return matches.get()
        if value.isdecimal():
            pk = Location._meta.pk.clean(value, None)
            return Location.active.get(pk=pk)
    except Location.MultipleObjectsReturned:
        raise ValidationError(_("Ambiguous identifier; use the location URL."))
    except (Location.DoesNotExist, Resolver404, ValueError, ValidationError):
        pass
    raise ValidationError(_("Location not found."))
