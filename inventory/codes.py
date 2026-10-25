"""
One way to read a code (docs/label-ids.md, "Codes: what counts where"): whatever someone typed, scanned or
pasted, wherever: the resolver behind the QR codes (i.zam.haus/…, /id/…, /id/?q=), ?q= of the lists, the
location fields and "Move here". resolve_code() reads, in this order:

1. an inventory location URL (/loc/<pk>/…), by its primary key;
2. a location's code, ignoring case, also as a label URL (HTTPS://I.ZAM.HAUS/R303.A), then a former code;
3. a reserved container's code (it is activated on first use);
4. the full short-name path of a location (HH-1.SK.K0520), still accepted;
5. a label ID (ZAMid), typed with or without the dash, with look-alikes (O/0, I/1), also with the location of
   an item label after it (K7R4XD/WH-1.R303.A);
6. where asked for, a number as a location's primary key (location fields);
and, if nothing matched, the same input read as typed by a scanner with another keyboard layout.

Location codes and label IDs never collide: new label IDs skip location codes (label_ids.services), and a
location code that reads as an existing label ID is refused (Location._validate_codes, LocationFormerCode).
"""
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.urls import Resolver404, resolve
from django.utils.translation import gettext as _

from .keyboard_layouts import layout_corrections
from .label_ids import core as label_id_core, parsing as label_id_parsing
from .label_ids.targets import RELATED_TARGETS
from .models import LabelId, Location, LocationFormerCode

LOCATION, RESERVED, LABEL_ID = "location", "reserved", "label_id"
UNKNOWN, INVALID, AMBIGUOUS = "unknown", "invalid", "ambiguous"
FOUND = (LOCATION, RESERVED, LABEL_ID)


@dataclass
class Found:
    kind: str
    location: Location = None  # LOCATION, RESERVED
    lid: LabelId = None  # LABEL_ID
    code: str = ""  # the canonical label ID (LABEL_ID, UNKNOWN)
    at: Location = None  # the location an item label names after the ID
    reason: str = ""  # INVALID: "malformed" or "checksum"; AMBIGUOUS: the message

    @property
    def key(self):
        return self.kind, self.location.pk if self.location else None, self.code


def scan_prefixes():
    """Location labels start with the label host (LABEL_ID_BASE_URL, with the code), older ones with
    DEFAULT_URL or an earlier domain (DOMAIN_ALIASES)."""
    urls = (settings.LABEL_ID_BASE_URL, settings.DEFAULT_URL, *getattr(settings, "DOMAIN_ALIASES", ()))
    return [url.rstrip("/") + "/" for url in urls]


def locations_by_code(code):
    """Active locations with this code or former code, ignoring case (label QR codes are uppercase)."""
    found = list(Location.active.filter(unique_identifier__iexact=code))
    if not found:
        former = LocationFormerCode.objects.filter(code__iexact=code, location__is_deleted=False,
                                                   location__is_reserved=False)
        found = list({entry.location for entry in former.select_related("location") if entry.location})
    return found


def reserved_by_code(code):
    """The reserved container (not activated yet, see ContainerActivateView) with this code, ignoring case, or None."""
    code = (code or "").strip()
    if not code:
        return None
    return Location.objects.filter(is_reserved=True, is_deleted=False, unique_identifier__iexact=code).first()


def _location_url(raw):
    """The location an inventory URL (/loc/<pk>/<code>) names, by its primary key, or None."""
    try:
        url = urlsplit(raw)
    except ValueError:  # e.g. a broken host in brackets
        return None
    if url.scheme and url.scheme not in ("http", "https"):
        return None
    try:
        match = resolve(unquote(url.path), urlconf=settings.ROOT_URLCONF)  # also on the resolver hosts
    except Resolver404:
        return None
    if match.url_name not in ("view_location", "view_location2"):
        return None
    return Location.active.filter(pk=match.kwargs["pk"]).first()


def _read(raw, numbers_are_pks):
    if "/" in raw and (location := _location_url(raw)) is not None:
        return Found(LOCATION, location=location)
    code = label_id_parsing.strip_url(raw)
    if not code:
        return Found(INVALID, reason="malformed")
    locations = locations_by_code(code)
    if len(locations) == 1:
        return Found(LOCATION, location=locations[0])
    if len(locations) > 1:
        return Found(AMBIGUOUS, reason=_("Ambiguous identifier; use the location URL."))
    if (reserved := reserved_by_code(code)) is not None:
        return Found(RESERVED, location=reserved)
    if (by_path := Location.active.filter(locatable_identifier__iexact=code).first()) is not None:
        return Found(LOCATION, location=by_path)
    try:
        lid_code = label_id_parsing.code_from_scan(code)
    except label_id_core.InvalidLabelId as error:
        if numbers_are_pks and code.isdecimal() and (location := Location.active.filter(pk=int(code)).first()):
            return Found(LOCATION, location=location)
        return Found(INVALID, reason=error.args[0])
    at = code.partition("/")[2]
    at_locations = locations_by_code(at) if at else []
    lid = LabelId.objects.select_related(*RELATED_TARGETS).filter(pk=lid_code).first()
    return Found(LABEL_ID if lid else UNKNOWN, lid=lid, code=lid_code,
                 at=at_locations[0] if len(at_locations) == 1 else None)


def resolve_code(text, *, numbers_are_pks=False):
    """What `text` names (Found); see the module's docstring for the order."""
    raw = (text or "").strip()
    if not raw:
        return Found(INVALID, reason="malformed")
    found = _read(raw, numbers_are_pks)
    if found.kind in FOUND or found.kind == AMBIGUOUS:
        return found
    # Label URLs start with a known domain; a garbled start reveals which scanner and host layouts were mixed up.
    readings = {}
    for corrected in {corrected for prefix in scan_prefixes() for corrected in layout_corrections(raw, prefix)}:
        reading = _read(corrected, numbers_are_pks)
        if reading.kind in FOUND:
            readings[reading.key] = reading
    if len(readings) > 1:
        return Found(AMBIGUOUS, reason=_("Ambiguous scan; check the keyboard layout of the scanner."))
    return next(iter(readings.values()), found)


def label_id_location(found):
    """The location an assigned label ID belongs to (not deleted, not reserved), or None."""
    lid = found.lid
    if found.kind != LABEL_ID or lid.status != LabelId.Status.ASSIGNED or lid.location is None:
        return None
    return None if lid.location.is_deleted or lid.location.is_reserved else lid.location


def reads_as_label_id(code):
    """The existing label ID a location code would be read as (resolve_code tries codes first), or None."""
    try:
        canonical = label_id_parsing.code_from_scan(code)
    except label_id_core.InvalidLabelId:
        return None
    return LabelId.objects.filter(pk=canonical).first()
