"""
The only code that changes the state of ZAM IDs. Every transition locks the row,
so two people scanning the same fresh label cannot both claim it.
"""
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from ..models import ZamId
from . import core
from .targets import CLAIMABLE_FIELDS, FK_TARGET_FIELDS

MAX_BATCH = 1000


class ZamIdError(Exception):
    """A state change that is not allowed; the message is meant for the user."""


def target_field_for(obj):
    """The ZamId column that can point at `obj` (an instance or a model class), or None."""
    cls = obj if isinstance(obj, type) else type(obj)
    for field in FK_TARGET_FIELDS:
        if issubclass(cls, ZamId._meta.get_field(field).related_model):
            return field
    return None


def generate_batch(count, batch="", user=None):
    if not 1 <= count <= MAX_BATCH:
        raise ZamIdError(_("Generate between 1 and %(max)d IDs at a time.") % {"max": MAX_BATCH})
    created = []
    with transaction.atomic():
        while len(created) < count:
            try:
                with transaction.atomic():
                    created.append(ZamId.objects.create(code=core.generate(), batch=batch, created_by=user))
            except IntegrityError:
                continue  # collision with an existing code: draw again
    return created


def _lock(code):
    try:
        return ZamId.objects.select_for_update().get(pk=code)
    except ZamId.DoesNotExist:
        raise ZamIdError(_("The ID %(code)s does not exist.") % {"code": core.display(code)})


def _require_reserved(zid):
    if zid.status == ZamId.Status.ASSIGNED:
        raise ZamIdError(_("The ID %(code)s is already in use.") % {"code": zid.display})
    if zid.status == ZamId.Status.RETIRED:
        raise ZamIdError(_("The ID %(code)s has been retired.") % {"code": zid.display})


def _assign(zid, field, value, user):
    setattr(zid, field, value)
    zid.status = ZamId.Status.ASSIGNED
    zid.assigned_at = timezone.now()
    zid.assigned_by = user
    try:
        with transaction.atomic():
            zid.save()
    except IntegrityError:
        # Another ID was assigned to the same target concurrently.
        raise ZamIdError(_("This already has an ID. Retire it first."))
    return zid


def claim(code, target, user):
    """Permanently link a reserved ID to an item or location."""
    field = target_field_for(target)
    if field not in CLAIMABLE_FIELDS:
        raise ZamIdError(_("IDs cannot be claimed for this kind of object."))
    if getattr(target, "is_deleted", False):
        raise ZamIdError(_("Deleted objects cannot get an ID."))
    with transaction.atomic():
        zid = _lock(code)
        _require_reserved(zid)
        current = ZamId.objects.assigned().filter(**{field: target}).first()
        if current:
            raise ZamIdError(_("%(target)s already has the ID %(code)s. Retire it first.")
                             % {"target": target, "code": current.display})
        return _assign(zid, field, target, user)


def assign_url(code, url, user):
    """Permanently link a reserved ID to an arbitrary http(s) URL (admin only)."""
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        raise ZamIdError(_("Enter a valid http or https URL."))
    with transaction.atomic():
        zid = _lock(code)
        _require_reserved(zid)
        return _assign(zid, "url", url, user)


def retire(code, user, note=""):
    """Take a label out of use. The ID keeps its target and is never reused."""
    with transaction.atomic():
        zid = _lock(code)
        if zid.status == ZamId.Status.RETIRED:
            raise ZamIdError(_("The ID %(code)s has been retired.") % {"code": zid.display})
        zid.status = ZamId.Status.RETIRED
        zid.retired_at = timezone.now()
        zid.retired_by = user
        if note:
            zid.note = f"{zid.note}\n{note}".strip()
        zid.save()
        return zid


def mark_printed(codes):
    return ZamId.objects.filter(pk__in=list(codes)).update(printed_at=timezone.now())
