"""
Bootstrap Icons (MIT, inventory/static/inventory/vendor/bootstrap-icons), inlined into the
page so they need no requests. Only the icons in use are vendored; to add one, copy its SVG
from https://icons.getbootstrap.com (version 1.11.3) into that folder.
"""
import re
from functools import lru_cache

from django.contrib.staticfiles import finders
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe

ICON_DIR = "inventory/vendor/bootstrap-icons/icons"


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
