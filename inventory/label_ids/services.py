"""
The only code that changes the state of label IDs. Every transition locks the row,
so two people scanning the same fresh label cannot both claim it.
"""
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from ..models import LabelId, Location, LocationFormerCode
from . import core
from .targets import CLAIMABLE_FIELDS

MAX_BATCH = 1000


class LabelIdError(Exception):
    """A state change that is not allowed; the message is meant for the user."""


target_field_for = LabelId.target_field_for


def is_location_code(code):
    """A code, current or former and in any case, of a location (deleted ones included)."""
    return (Location.objects.filter(unique_identifier__iexact=code).exists()
            or LocationFormerCode.objects.filter(code__iexact=code).exists())


def generate_batch(count, batch="", user=None):
    if not 1 <= count <= MAX_BATCH:
        raise LabelIdError(_("Generate between 1 and %(max)d IDs at a time.") % {"max": MAX_BATCH})
    created = []
    with transaction.atomic():
        while len(created) < count:
            code = core.generate()
            if is_location_code(code):
                continue  # the resolver would lead to the location: draw again
            try:
                with transaction.atomic():
                    created.append(LabelId.objects.create(code=code, batch=batch, created_by=user))
            except IntegrityError:
                continue  # collision with an existing code: draw again
    return created


def _lock(code):
    try:
        return LabelId.objects.select_for_update().get(pk=code)
    except LabelId.DoesNotExist:
        raise LabelIdError(_("The ID %(code)s does not exist.") % {"code": core.display(code)})


def _require_reserved(lid):
    if lid.status == LabelId.Status.ASSIGNED:
        raise LabelIdError(_("The ID %(code)s is already in use.") % {"code": lid.display})
    if lid.status == LabelId.Status.RETIRED:
        raise LabelIdError(_("The ID %(code)s has been retired.") % {"code": lid.display})


def _assign(lid, field, value, user):
    setattr(lid, field, value)
    lid.status = LabelId.Status.ASSIGNED
    lid.assigned_at = timezone.now()
    lid.assigned_by = user
    try:
        with transaction.atomic():
            lid.save()
    except IntegrityError:
        # Another ID was assigned to the same target concurrently.
        raise LabelIdError(_("This already has an ID. Retire it first."))
    return lid


def claim(code, target, user):
    """Permanently link a reserved ID to an item, location or unique item."""
    field = target_field_for(target)
    if field not in CLAIMABLE_FIELDS:
        raise LabelIdError(_("IDs cannot be claimed for this kind of object."))
    if getattr(target, "is_deleted", False):
        raise LabelIdError(_("Deleted objects cannot get an ID."))
    if getattr(target, "is_disposed", False):
        raise LabelIdError(_("Objects removed from the inventory cannot get an ID."))
    with transaction.atomic():
        lid = _lock(code)
        _require_reserved(lid)
        current = LabelId.objects.assigned().filter(**{field: target}).first()
        if current:
            raise LabelIdError(_("%(target)s already has the ID %(code)s. Retire it first.")
                             % {"target": target, "code": current.display})
        return _assign(lid, field, target, user)


def generate_and_claim(target, user, batch="unique_item"):
    """Give `target` a brand-new ID right away, so no unassigned label is ever created."""
    with transaction.atomic():
        lid, = generate_batch(1, batch=batch, user=user)
        return claim(lid.code, target, user)


def assign_url(code, url, user):
    """Permanently link a reserved ID to an arbitrary http(s) URL (admin only)."""
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        raise LabelIdError(_("Enter a valid http or https URL."))
    with transaction.atomic():
        lid = _lock(code)
        _require_reserved(lid)
        return _assign(lid, "url", url, user)


def retire(code, user, note=""):
    """Take a label out of use. The ID keeps its target and is never reused."""
    with transaction.atomic():
        lid = _lock(code)
        if lid.status == LabelId.Status.RETIRED:
            raise LabelIdError(_("The ID %(code)s has been retired.") % {"code": lid.display})
        lid.status = LabelId.Status.RETIRED
        lid.retired_at = timezone.now()
        lid.retired_by = user
        if note:
            lid.note = f"{lid.note}\n{note}".strip()
        lid.save()
        return lid


def mark_printed(codes):
    return LabelId.objects.filter(pk__in=list(codes)).update(printed_at=timezone.now())
