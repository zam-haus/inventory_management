"""
Bootstrap Icons (MIT, inventory/static/inventory/vendor/bootstrap-icons), inlined into the
page so they need no requests. Only the icons in use are vendored; to add one, copy its SVG
from https://icons.getbootstrap.com (version 1.11.3) into that folder. Location types choose theirs
among them (LocationType.icon, available()).
"""
import re
from functools import lru_cache
from pathlib import Path

from django.contrib.staticfiles import finders
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe

ICON_DIR = "inventory/vendor/bootstrap-icons/icons"


@lru_cache(maxsize=None)
def exists(name):
    return bool(re.fullmatch(r"[a-z0-9-]+", name or "")) and finders.find(f"{ICON_DIR}/{name}.svg") is not None


def available():
    """The names of the vendored icons, sorted."""
    folder = Path(finders.find(ICON_DIR))
    return sorted(path.stem for path in folder.glob("*.svg"))


@lru_cache(maxsize=None)
def _svg(name):
    path = finders.find(f"{ICON_DIR}/{name}.svg")
    if path is None:
        raise ValueError(f"Unknown icon {name!r}: add its SVG to {ICON_DIR}.")
    with open(path, encoding="utf-8") as file:
        svg = file.read().strip()
    # Sized like the surrounding text; buttons carry the accessible name themselves.
    svg = svg.replace(' width="16" height="16"', ' width="1em" height="1em"', 1)
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


def icon(name, classes=""):
    svg = _svg(name)
    if classes:
        svg = svg.replace(f'class="bi bi-{name}"', f'class="bi bi-{name} {escape(classes)}"', 1)
    return mark_safe(svg)


def add_icon(name):
    """The icon of what an "add" button adds with a plus badge at its top right (docs/icons.md), so that each such
    button shows what it adds, also without its text (actions.js)."""
    return format_html('<span class="action-icon action-add-icon">{}{}</span>', icon(name, "action-add-kind"),
                       icon("plus-badge", "action-add-plus"))


def sprite(names, prefix, classes):
    """The icons as <symbol>s (ids prefix-name), drawn once per page; use() shows one. Long lists stay small: an icon
    inline is about a kilobyte, a reference to it a few bytes."""
    symbols = []
    for name in sorted(names):
        svg = _svg(name)
        view_box = re.search(r'viewBox="([^"]*)"', svg).group(1)
        inner = svg[svg.index(">") + 1:svg.rindex("</svg>")]
        symbols.append(format_html('<symbol id="{}-{}" viewBox="{}">{}</symbol>', prefix, name, view_box, mark_safe(inner)))
    return format_html('<svg class="{}" aria-hidden="true" focusable="false">{}</svg>', classes,
                       format_html_join("", "{}", ((symbol,) for symbol in symbols)))


def use(name, prefix, classes):
    """An icon of a sprite()."""
    return format_html('<svg class="{}" width="1em" height="1em" aria-hidden="true" focusable="false">'
                       '<use href="#{}-{}"/></svg>', classes, prefix, name)


# The icons of what locations, items and unique items are (docs/icons.md): before their names everywhere, from a
# sprite drawn once on every page (type_icon_sprite in base.html), so that lists, rows loaded later and suggestions
# of choice fields need only a reference.
TYPE_ICONS = ("geo-alt", "bookshelf", "eurobox-open", "boxes", "box-star-stack", "box-star")


def type_icon_names():
    """TYPE_ICONS and the icons location types choose (LocationType.icon): all that the sprite holds. Asked once per
    request (result rows ask for each row)."""
    from .actor import current_request
    from .models import LocationType

    request = current_request()
    names = getattr(request, "type_icon_names", None)
    if names is None:
        names = {*TYPE_ICONS, *LocationType.objects.exclude(icon="").values_list("icon", flat=True)}
        if request is not None:
            request.type_icon_names = names
    return names


def type_icon(name):
    """The icon of a location's type or an item's kind, before its name: a reference to the page's sprite."""
    return use(name, "type-icon", f"bi bi-{name} type-icon")


def type_icon_sprite(database=True):
    """Takes no room, also on pages without the app's styles (standalone pages, the print view). Without the
    database (error pages, which show no locations) only TYPE_ICONS."""
    svg = sprite(type_icon_names() if database else TYPE_ICONS, "type-icon", "type-icon-sprite")
    return mark_safe(svg.replace("<svg ", '<svg style="position:absolute;width:0;height:0;overflow:hidden" ', 1))

