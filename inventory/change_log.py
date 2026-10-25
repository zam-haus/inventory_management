"""
Writes the change log (models.ChangeLog, docs/change-log.md).

Signal handlers log every save and deletion of items, unique items, stock entries,
locations, photos, files and barcodes, whatever saves them: forms, dialogs, the
admin, dissolutions. Soft deletions (soft_delete.soft_deleted), label IDs
(label_ids.services), printed labels (record_print) and the stock dialog
(record_stock) are logged explicitly.

Who acted is the current user (actor.current_actor()); `change_context()` tells
through which part of the application (else: the admin or the website, from the
request) and, for stock changes, why. Increases without a given reason count as
found during a recount.
"""
import datetime
import functools
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.translation import gettext as _, gettext_lazy

from .actor import current_actor, current_request
from .soft_delete import soft_deleted

logger = logging.getLogger(__name__)
_context = ContextVar("change_log", default=None)


@contextmanager
def change_context(*, source=None, actor=None, decrease_reason=None, increase_reason=None, note="",
                   log=True, log_stock=True):
    """Attribute the changes made inside; `log=False` suppresses all entries, `log_stock=False` only those of
    stock entries (for code that logs them itself)."""
    outer = _context.get() or {}
    given = {"source": source, "actor": actor, "decrease_reason": decrease_reason,
             "increase_reason": increase_reason, "note": note}
    token = _context.set({
        **outer, **{key: value for key, value in given.items() if value},
        "log": log and outer.get("log", True), "log_stock": log_stock and outer.get("log_stock", True),
    })
    try:
        yield
    finally:
        _context.reset(token)


def current_context():
    return _context.get() or {}


def _actor():
    actor = current_context().get("actor") or current_actor()
    return actor if actor is not None and actor.is_authenticated else None


def _source():
    from .models import ChangeLog
    if source := current_context().get("source"):
        return source
    request = current_request()
    if request is None:
        return ChangeLog.Source.OTHER
    return ChangeLog.Source.ADMIN if request.path.startswith(reverse("admin:index")) else ChangeLog.Source.WEB


def record(action, subject, *, label=None, item=None, unique_item=None, location=None, other_location=None,
           changes=(), reason="", details=None, sale_value=None, note="", request_id=None, actor=None,
           source=None, using=None, force=False):
    """One log entry about `subject` (an instance, or a (model name, pk) pair), shown on the pages of the
    given item, unique item and locations."""
    from .models import ChangeLog
    if not force and not current_context().get("log", True):
        return None
    if isinstance(subject, tuple):
        subject_type, subject_id = subject
    else:
        subject_type, subject_id = subject._meta.model_name, subject.pk
    actor = actor if actor is not None else _actor()
    return ChangeLog.objects.using(using).create(
        actor=actor, actor_name=actor.get_username() if actor is not None else "",
        source=source or _source(), action=action,
        subject_type=subject_type, subject_id=subject_id,
        subject_label=(label if label is not None else subject_label(subject))[:512],
        item=item, unique_item=unique_item, location=location, other_location=other_location,
        changes=list(changes), reason=reason, details=details or {}, sale_value=sale_value,
        note=note or current_context().get("note", ""), request_id=request_id,
    )


def subject_label(subject):
    if isinstance(subject, tuple):
        return ""
    if subject._meta.model_name == "uniqueitem":
        # Without caching the label ID on the instance: a new unique item gets its ID after saving.
        cached = "_label_code" in subject.__dict__
        label = str(subject)
        if not cached:
            subject.__dict__.pop("_label_code", None)
        return label
    if hasattr(subject, "title_with_code"):  # a location
        return subject.title_with_code
    if hasattr(subject, "display_name") and not hasattr(subject, "unique_identifier"):  # a file
        return subject.display_name
    if subject._meta.model_name == "itemimage":
        return subject.description or Path(subject.image.name).name
    if subject._meta.model_name == "itemlocation":
        return str(subject.item)
    return str(subject)


# What is logged of each model: its fields, and those of them that are internal (only shown with
# inventory.view_internal_details). Computed identifiers are left out. When removing or renaming a field
# here, add its old name to FORMER_FIELDS, so that older entries keep a readable label.
TRACKED = {
    "item": (("name", "description", "category", "kind", "measurement_unit", "sale_price", "for_sale",
              "last_purchase_date", "last_purchase_price", "procurement_source", "usage_level", "is_deleted"),
             {"last_purchase_price"}),
    "uniqueitem": (("item", "name", "location", "usage_level", "warranty_until", "notes", "responsible_team",
                    "responsible_user", "owner_user", "owner_first_name", "owner_contact", "purchase_date",
                    "purchase_price", "procurement_source", "disposed_at", "disposal_reason", "disposal_note"),
                   {"responsible_user", "owner_user", "owner_contact", "purchase_price"}),
    "location": (("type", "name", "short_name", "purpose", "physical_description", "overview_photo",
                  "parent_location", "axis", "fire_load_free", "outdoor", "is_deleted"), set()),
    "itemlocation": (("item", "location", "amount"), set()),
    "itemimage": (("image", "description", "is_primary", "unique_item"), set()),
    "itemfile": (("file", "description", "internal", "unique_item"), set()),
    "itembarcode": (("data", "type"), set()),
}
# Shown by the action instead of as changed fields.
NOT_LISTED = {"is_deleted", "disposed_at", "disposal_reason", "disposal_note"}
TEXT_LIMIT = 2000
# Labels of fields that older entries name but the models no longer have: {(model name, field): label}.
FORMER_FIELDS = {
    # ("location", "summary"): gettext_lazy("summary"),
}


def missing_fields():
    """(model name, field) of TRACKED that the models do not have (any more)."""
    missing = []
    for name, (fields, _internal) in TRACKED.items():
        meta = apps.get_model("inventory", name)._meta
        for field in fields:
            try:
                meta.get_field(field)
            except FieldDoesNotExist:
                missing.append((name, field))
    return missing


@checks.register()
def check_tracked_fields(app_configs, **kwargs):
    return [checks.Warning(f"The change log tracks {name}.{field}, which does not exist; it is not logged.",
                           hint="Remove it from TRACKED in inventory/change_log.py (and add it to FORMER_FIELDS).",
                           id="inventory.W001")
            for name, field in missing_fields()]


@functools.cache
def _fields(model):
    """The model's tracked fields; one that no longer exists is left out with a warning, so saving still works."""
    names, _internal = TRACKED[model._meta.model_name]
    fields = []
    for name in names:
        try:
            fields.append(model._meta.get_field(name))
        except FieldDoesNotExist:
            logger.warning("Change log: %s.%s is tracked but does not exist; it is not logged (TRACKED in %s).",
                           model._meta.model_name, name, __name__)
    return fields


def _stored(model, pk, using):
    return model._base_manager.using(using).filter(pk=pk).values(
        *(field.attname for field in _fields(model))).first()


def value(field, raw):
    """A stored value as text, as people read it ("" for none)."""
    if raw is None or raw == "":
        return ""
    if field.is_relation:
        related = field.related_model._base_manager.filter(pk=raw).first()
        if related is None:
            return f"#{raw}"
        if isinstance(related, AbstractBaseUser):
            return related.get_username()
        return related.title_with_code if hasattr(related, "title_with_code") else str(related)
    if field.choices:
        return str(dict(field.flatchoices).get(raw, raw))
    if isinstance(raw, bool):
        return _("yes") if raw else _("no")
    if isinstance(raw, datetime.datetime):
        return formats.date_format(timezone.localtime(raw), "SHORT_DATETIME_FORMAT")
    if isinstance(raw, datetime.date):
        return formats.date_format(raw, "SHORT_DATE_FORMAT")
    if isinstance(raw, Decimal):
        return formats.number_format(raw, use_l10n=True)
    if isinstance(field, models.FileField):
        return Path(str(raw)).name
    text = str(raw)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def _changes(model, before, after, skip=()):
    _names, internal = TRACKED[model._meta.model_name]
    changes = []
    for field in _fields(model):
        if field.name in skip or field.name in NOT_LISTED or before[field.attname] == after[field.attname]:
            continue
        changes.append({"field": field.name, "before": value(field, before[field.attname]),
                        "after": value(field, after[field.attname]), "internal": field.name in internal})
    return changes


def _location(pk, using):
    from .models import Location
    return Location.objects.using(using).filter(pk=pk).first() if pk else None


def _remember(sender, instance, raw=False, using=None, **kwargs):
    instance._change_log_before = None if raw or instance.pk is None else _stored(sender, instance.pk, using)


def _saved(sender, instance, created, raw=False, using=None, **kwargs):
    before = instance.__dict__.pop("_change_log_before", None)
    if raw or not current_context().get("log", True):
        return
    name = sender._meta.model_name
    if name == "itemlocation":
        return _stock_saved(instance, before, using)
    if before is None:
        return _created(instance, using)
    after = _stored(sender, instance.pk, using)
    if after is None or after == before:
        return
    links = _links(instance)
    if name == "location":
        return _location_saved(instance, before, after, links, using)
    if name == "uniqueitem":
        return _unique_item_saved(instance, before, after, links, using)
    changes = _changes(sender, before, after)
    if name == "item" and before["is_deleted"] != after["is_deleted"]:
        from .models import ChangeLog
        action = ChangeLog.Action.DELETED if after["is_deleted"] else ChangeLog.Action.RESTORED
        return record(action, instance, changes=changes, using=using, **links)
    if changes:
        instance._change_log_entry = record("changed", instance, changes=changes, using=using,
                                            details=_attachment_details(instance), **links)


def _links(instance):
    """The pages an entry about the instance is shown on."""
    name = instance._meta.model_name
    if name == "item":
        return {"item": instance}
    if name == "uniqueitem":
        return {"unique_item": instance}
    if name == "location":
        return {"location": instance}
    # Photos, files and barcodes: on the page of the item or the unique item they belong to.
    if getattr(instance, "unique_item_id", None):
        return {"unique_item": instance.unique_item}
    return {"item": instance.item}


def _attachment_details(instance):
    return {"internal": True} if getattr(instance, "internal", False) else None


def _created(instance, using):
    from .models import ChangeLog
    name = instance._meta.model_name
    links = _links(instance)
    if name == "location":
        # Also on the page of the location it is in; its responsible teams are added (_teams_changed).
        instance._change_log_entry = record(
            ChangeLog.Action.CREATED, instance, other_location=_location(instance.parent_location_id, using),
            using=using, **links)
        return instance._change_log_entry
    if name == "uniqueitem":
        return record(ChangeLog.Action.CREATED, instance, location=_location(instance.location_id, using),
                      using=using, **links)
    if name in ("itemimage", "itemfile", "itembarcode"):
        return record(ChangeLog.Action.ATTACHED, instance, details=_attachment_details(instance), using=using,
                      **links)
    return record(ChangeLog.Action.CREATED, instance, using=using, **links)


def _location_saved(instance, before, after, links, using):
    from .models import ChangeLog
    changes = _changes(type(instance), before, after)
    if before["is_deleted"] != after["is_deleted"]:
        action = ChangeLog.Action.DELETED if after["is_deleted"] else ChangeLog.Action.RESTORED
        return record(action, instance, changes=changes, other_location=_location(after["parent_location_id"], using),
                      using=using, **links)
    if before["parent_location_id"] != after["parent_location_id"]:
        # Shown on the page of the location it left as well.
        instance._change_log_entry = record(
            ChangeLog.Action.MOVED, instance, changes=changes, using=using,
            other_location=_location(before["parent_location_id"], using), **links)
    elif changes:
        instance._change_log_entry = record(ChangeLog.Action.CHANGED, instance, changes=changes, using=using, **links)


def _unique_item_saved(instance, before, after, links, using):
    from .models import ChangeLog
    if before["disposed_at"] is None and after["disposed_at"] is not None:
        changes = _changes(type(instance), before, after, skip={"location"})
        return record(ChangeLog.Action.DISPOSED, instance, changes=changes, reason=after["disposal_reason"],
                      note=after["disposal_note"], location=_location(before["location_id"], using), using=using,
                      **links)
    if before["disposed_at"] is not None and after["disposed_at"] is None:
        changes = _changes(type(instance), before, after, skip={"location"})
        return record(ChangeLog.Action.RESTORED, instance, changes=changes,
                      location=_location(after["location_id"], using), using=using, **links)
    if before["location_id"] != after["location_id"]:
        # Shown on the pages of both locations.
        changes = _changes(type(instance), before, after, skip={"location"})
        return record(ChangeLog.Action.MOVED, instance, changes=changes, location=_location(after["location_id"], using),
                      other_location=_location(before["location_id"], using), using=using, **links)
    if changes := _changes(type(instance), before, after):
        return record(ChangeLog.Action.CHANGED, instance, changes=changes, using=using, **links)


def _number(amount):
    return None if amount is None else str(amount)


def record_stock(entry, *, item, location, before, after, removed=False, added=False, change=None, reason=None,
                 note="", request_id=None, using=None, force=False):
    """A stock entry (or a (model name, pk) pair) changed from `before` to `after` (None: unknown); `change` is
    (direction, changed amount, estimated), None for quick-items. Unset reasons come from change_context()."""
    from .models import ChangeLog
    details = {"before": _number(before), "after": _number(after), "unit": item.measurement_unit.short}
    if removed:
        details["removed"] = True
    if added:
        details["added"] = True
    sale_value = None
    if change is not None:
        direction, amount, estimated = change
        if reason is None:
            default = ChangeLog.Reason.RECOUNT_FOUND if direction == ChangeLog.Direction.INCREASE else ChangeLog.Reason.OTHER
            reason = current_context().get(f"{direction}_reason") or default
        price = item.sale_price
        if amount is not None and price is not None:
            sale_value = (amount * price).quantize(Decimal("0.01"))
        details.update(direction=direction, amount=_number(amount), estimated=estimated,
                       unit_price=_number(price))
    return record(ChangeLog.Action.STOCK, entry, label=str(item), item=item, location=location,
                  reason=reason or "", details=details, sale_value=sale_value, note=note, request_id=request_id,
                  using=using, force=force)


def _stock_saved(entry, before, using):
    from .models import ChangeLog, Item, Location, stock_change
    context = current_context()
    if not context.get("log_stock", True):
        return
    item = Item.objects.using(using).select_related("measurement_unit").get(pk=entry.item_id)
    after = _stored(type(entry), entry.pk, using)
    if before is None:
        # Newly stored stock has a reason (and a sale value) only if one is given, e.g. a purchase.
        change = None
        if after["amount"] is not None and context.get("increase_reason"):
            change = stock_change(Decimal(0), after["amount"])
        return record_stock(entry, item=item, location=_location(entry.location_id, using), before=None,
                            after=after["amount"], added=True, change=change, using=using)
    if before["amount"] != after["amount"]:
        # A change combined with a move is logged where the stock was.
        record_stock(entry, item=item, location=Location.objects.using(using).get(pk=before["location_id"]),
                     before=before["amount"], after=after["amount"],
                     change=stock_change(before["amount"], after["amount"]), using=using)
    if before["location_id"] != after["location_id"]:
        record(ChangeLog.Action.MOVED, entry, label=str(item), item=item, using=using,
               location=_location(after["location_id"], using), other_location=_location(before["location_id"], using))
    if before["item_id"] != after["item_id"]:
        record(ChangeLog.Action.CHANGED, entry, label=str(item), item=item, using=using,
               location=_location(after["location_id"], using), changes=_changes(type(entry), before, after,
                                                                                 skip={"amount", "location"}))


def _deletes(origin, model):
    """Whether a deletion that started at `origin` removes records of `model` (they cannot be linked)."""
    if isinstance(origin, model):
        return True
    return isinstance(origin, models.QuerySet) and origin.model is model


def _deleted(sender, instance, using, origin=None, **kwargs):
    """A record removed for good: soft-deleted items and locations, quick-items, stock entries, attachments."""
    from .models import ChangeLog, Item, Location, UniqueItem, stock_change
    if not current_context().get("log", True):
        return
    name = sender._meta.model_name
    keep_item = not _deletes(origin, Item)
    if name == "itemlocation":
        if not current_context().get("log_stock", True):
            return
        item = Item.objects.using(using).select_related("measurement_unit").filter(pk=instance.item_id).first()
        if item is None:
            return
        location = _location(instance.location_id, using) if not _deletes(origin, Location) else None
        if keep_item:
            return record_stock(instance, item=item, location=location, before=instance.amount, after=None,
                                removed=True, change=stock_change(instance.amount, None), using=using)
        # Removed with its item (a quick-item): shown on the location's page only.
        return record(ChangeLog.Action.STOCK, instance, label=str(item), location=location, using=using,
                      details={"before": _number(instance.amount), "after": None, "removed": True,
                               "unit": item.measurement_unit.short})
    if name in ("itemimage", "itemfile", "itembarcode"):
        # Removed along with their item: the item's deletion is logged.
        if not keep_item or _deletes(origin, UniqueItem):
            return
        return record(ChangeLog.Action.DETACHED, instance, details=_attachment_details(instance), using=using,
                      **_links(instance))
    if name == "location":
        return record(ChangeLog.Action.DELETED, instance, using=using,
                      other_location=_location(instance.parent_location_id, using))
    return record(ChangeLog.Action.DELETED, instance, using=using)


def _soft_deleted(sender, instance, using, **kwargs):
    from .models import ChangeLog
    if not current_context().get("log", True) or sender._meta.model_name not in ("item", "location"):
        return
    other = {"other_location": _location(instance.parent_location_id, using)} if hasattr(instance, "parent_location_id") else {}
    record(ChangeLog.Action.DELETED, instance, using=using, **_links(instance), **other)


def _teams_changed(sender, instance, action, reverse, pk_set, using, **kwargs):
    """Responsible teams of a location: one entry per form save, merged with the entry of the save itself."""
    from .models import Location
    if reverse or not isinstance(instance, Location) or not current_context().get("log", True):
        return
    names = lambda: ", ".join(sorted(team.group.name for team in instance.responsible_teams.select_related("group")))
    if action in ("pre_add", "pre_remove", "pre_clear"):
        if "_change_log_teams" not in instance.__dict__:
            instance._change_log_teams = names()
        return
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    before, after = instance._change_log_teams, names()
    change = {"field": "responsible_teams", "before": before, "after": after, "internal": False}
    entry = instance.__dict__.get("_change_log_entry")
    if entry is not None:
        entry.changes = [c for c in entry.changes if c["field"] != "responsible_teams"]
        if before != after:
            entry.changes.append(change)
        entry.save(update_fields=["changes"])
    elif before != after:
        instance._change_log_entry = record("changed", instance, changes=[change], location=instance, using=using)


def record_label_id(lid, event):
    """A label ID was assigned to its target or retired ("assigned", "retired")."""
    from .models import ChangeLog
    target = lid.target
    if target is None or isinstance(target, str):
        return None  # URLs have no page here
    return record(ChangeLog.Action.LABEL_ID, target, details={"code": lid.display, "event": event}, **_links(target))


def record_print(job, layout_name):
    """A finished print job: one entry per label, on the pages of what it is for. Whoever printed it acted."""
    from .models import ChangeLog, Item, LabelId, Location, UniqueItem
    details = {"template": layout_name, "printer": str(job.printer) if job.printer_id else "",
               "medium": str(job.medium) if job.medium_id else "", "copies": job.copies, "job": job.pk}
    existing = lambda model, pk: model.objects.filter(pk=pk).first() if pk else None
    for label in job.snapshot:
        kind = label.get("type")
        links = {}
        if kind == "location":
            links["location"] = existing(Location, label.get("id"))
        elif kind == "item":
            links.update(item=existing(Item, label.get("id")), location=existing(Location, label.get("location_id")))
        elif kind == "uniqueitem":
            links["unique_item"] = existing(UniqueItem, label.get("id"))
        elif kind == "labelid":
            lid = LabelId.objects.filter(pk=label.get("code")).first()
            target = lid.target if lid else None
            if target is not None and not isinstance(target, str):
                links.update(_links(target))
        if not any(links.values()):
            continue
        subject = next(value for value in links.values() if value is not None)
        record(ChangeLog.Action.PRINTED, subject, details=details, actor=job.user,
               source=ChangeLog.Source.PRINT, force=True, **links)


def _models(*names):
    return [apps.get_model("inventory", name) for name in names]


def connect():
    """Called once the models are ready (InventoryConfig.ready)."""
    for model in _models(*TRACKED):
        pre_save.connect(_remember, sender=model, dispatch_uid=f"change_log_remember_{model._meta.model_name}")
        post_save.connect(_saved, sender=model, dispatch_uid=f"change_log_saved_{model._meta.model_name}")
        post_delete.connect(_deleted, sender=model, dispatch_uid=f"change_log_deleted_{model._meta.model_name}")
    for model in _models("item", "location"):
        soft_deleted.connect(_soft_deleted, sender=model, dispatch_uid=f"change_log_soft_{model._meta.model_name}")
    location, = _models("location")
    m2m_changed.connect(_teams_changed, sender=location.responsible_teams.through, dispatch_uid="change_log_teams")


def actor_label(user):
    """Who acted, for people allowed to see it: "Vorname N. (username)"."""
    first, last = user.first_name.strip(), user.last_name.strip()
    name = " ".join(part for part in (first, f"{last[0]}." if last else "") if part)
    return f"{name} ({user.get_username()})" if name else user.get_username()

