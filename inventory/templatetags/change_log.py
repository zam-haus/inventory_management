"""The last changes on the pages of items, unique items and locations (docs/change-log.md)."""
from decimal import Decimal

from django import template
from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.text import Truncator
from django.utils.translation import gettext as _, ngettext

from .. import location_display
from ..change_log import APP_FIELDS, FORMER_FIELDS, actor_label
from ..label_ids import naming
from ..models import ChangeLog, Item, Location, UniqueItem, format_amount

register = template.Library()

VALUE_LENGTH = 80


def field_label(subject_type, name):
    """The field's current label, else the one it had (FORMER_FIELDS) or an app gave it (APP_FIELDS), else its name."""
    try:
        return str(apps.get_model("inventory", subject_type)._meta.get_field(name).verbose_name)
    except (LookupError, FieldDoesNotExist):
        return str(FORMER_FIELDS.get((subject_type, name)) or APP_FIELDS.get((subject_type, name)) or name)


def short(text):
    return Truncator(text).chars(VALUE_LENGTH) if text else "–"


def location_link(location, fallback=""):
    if location is None:
        return fallback or "–"
    return location_display.label_html(location, url=None if location.is_deleted else location.get_absolute_url())


def link(obj, text):
    """A link to the page of an item or unique item; deleted items have none."""
    if obj is None or getattr(obj, "is_deleted", False):
        return text
    return format_html('<a href="{}">{}</a>', obj.get_absolute_url(), text)


def stock_lines(entry):
    details = entry.details
    unit = details.get("unit", "")
    amount = lambda key: format_amount(None if details.get(key) is None else Decimal(details[key]), unit)
    lines = []
    if details.get("direction"):
        sign = "+" if entry.is_increase else "−"
        changed = (_("unknown amount") if details.get("amount") is None
                   else ("~" if details.get("estimated") else "") + amount("amount"))
        lines.append(f"{sign} {changed}" + (f" ({entry.get_reason_display()})" if entry.reason else ""))
    if details.get("added"):
        lines.append(_("Stored here: %(amount)s") % {"amount": amount("after")})
    elif details.get("removed"):
        lines.append(_("%(amount)s, removed from the location") % {"amount": amount("before")})
    else:
        lines.append(f"{amount('before')} → {amount('after')}")
    return lines


def describe(entry, page, user):
    """What the panel shows of an entry: its subject unless it is the page's (None: no page), and what changed."""
    internal = user.has_perm("inventory.view_internal_details")
    shown = {"entry": entry, "lines": [], "changes": [],
             # Label IDs as the installation calls them (LABEL_ID_NAME).
             "action": naming.NAME if entry.action == ChangeLog.Action.LABEL_ID else entry.get_action_display()}
    if user.has_perm("inventory.view_changelog_actor"):
        shown["actor"] = actor_label(entry.actor) if entry.actor is not None else entry.actor_name
    is_page = page is not None and (entry.subject_type, entry.subject_id) == (page._meta.model_name, page.pk)
    if entry.subject_type == "itemlocation" and isinstance(page, Location):
        shown["subject"] = link(entry.item, entry.subject_label)
    elif entry.subject_type == "itemlocation":
        if entry.action != ChangeLog.Action.MOVED:  # moves show both locations
            shown["subject"] = location_link(entry.location)
    elif entry.subject_type == "location" and not is_page:
        shown["subject"] = location_link(entry.location, entry.subject_label)
    elif entry.subject_type == "uniqueitem" and not is_page:
        shown["subject"] = link(entry.unique_item, entry.subject_label)
    elif entry.subject_type == "item" and not is_page:
        shown["subject"] = link(entry.item, entry.subject_label)
    elif not is_page:
        shown["subject"] = entry.subject_label  # names of internal files are shown on the pages, too
    if entry.action == ChangeLog.Action.MOVED and entry.subject_type != "location":
        shown["move"] = (location_link(entry.other_location), location_link(entry.location))
    if entry.action == ChangeLog.Action.STOCK:
        shown["lines"] = stock_lines(entry)
    elif entry.action == ChangeLog.Action.PRINTED:
        details = entry.details
        copies = details.get("copies", 1)
        shown["lines"] = [" · ".join(part for part in (
            details.get("template", ""),
            ngettext("%(count)d copy", "%(count)d copies", copies) % {"count": copies} if copies > 1 else "",
            details.get("printer", ""),
        ) if part)]
    elif entry.action == ChangeLog.Action.LABEL_ID:
        event = entry.details.get("event")
        text = _("%(code)s assigned") if event == "assigned" else _("%(code)s retired")
        shown["lines"] = [text % {"code": entry.details.get("code", "")}]
    elif entry.reason:
        shown["lines"] = [entry.get_reason_display()]
    for change in entry.changes:
        visible = internal or not change.get("internal")
        shown["changes"].append({
            "field": field_label(entry.subject_type, change["field"]), "internal": not visible,
            "before": short(change["before"]) if visible else "", "after": short(change["after"]) if visible else "",
        })
    return shown


def page_filter(page):
    if isinstance(page, Location):
        return Q(location=page) | Q(other_location=page), {"shown_on_location": page.pk}
    if isinstance(page, UniqueItem):
        return Q(unique_item=page), {"unique_item__id__exact": page.pk}
    if isinstance(page, Item):
        return Q(item=page), {"item__id__exact": page.pk}
    raise TypeError(page)


@register.inclusion_tag("inventory/change_log_panel.html", takes_context=True)
def change_log_panel(context, page):
    """The last settings.CHANGE_LOG_SHOWN changes shown on the page of `page`, for people allowed to see them."""
    user = context["request"].user
    if not user.has_perm("inventory.view_changelog") or settings.CHANGE_LOG_SHOWN <= 0:
        return {"change_log_entries": []}
    condition, admin_filter = page_filter(page)
    entries = (ChangeLog.objects.filter(condition)
               .select_related("actor", "item", "unique_item__item", "location", "other_location")
               [:settings.CHANGE_LOG_SHOWN])
    admin_url = ""
    if user.is_staff:
        admin_url = reverse("admin:inventory_changelog_changelist") + "?" + urlencode(admin_filter)
    return {"change_log_entries": [describe(entry, page, user) for entry in entries], "admin_url": admin_url,
            "panel": "location" if isinstance(page, Location) else "item"}
