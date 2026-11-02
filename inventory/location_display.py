"""
How locations are shown (docs/locations.md): the icon of its type first, then what people call it, its purpose, else
its name (the name small next to a purpose); its code after it, always alike: white monospace on muted grey (class
loc-code, inventory/locations.css). A path names each location above it so, too. Items and unique items have the
icon of their kind before their names (docs/icons.md). Template tags: {% load locations %}{% location_label location %},
{% location_path location %}, {% location_code code %}, {% item_label item %}, {% unique_item_label unique_item %}.
"""
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .icons import type_icon

# Icons of locations by what they are (LocationType.category, docs/icons.md); others, such as rooms, the pin.
CATEGORY_ICONS = {"storage_unit": "bookshelf", "container": "eurobox-open"}


def icon_name(location):
    """The icon of a location (inventory/icons.py), from its type's category; needs location.type."""
    return category_icon_name(location.type.category)


def category_icon_name(category):
    """The icon of the locations of a type's category ("storage_unit", "container", …)."""
    return CATEGORY_ICONS.get(category, "geo-alt")



def code_html(code, classes="", location=None):
    """A location code (short name, unique or locatable identifier) as a chip. With the location, the chip shows
    it in brief when clicked (location_info.js), also inside a link, which the name follows."""
    classes = f" {classes}" if classes else ""
    if location is None:
        return format_html('<span class="loc-code{}">{}</span>', classes, code)
    return format_html('<span class="loc-code{}" data-location-info="{}" role="button" tabindex="0" title="{}">{}</span>',
                       classes, location.pk, _("Location in brief"), code)


def label_html(location, code=None, url=None, subtitle=True, classes="", info=False, icon=True, mark=None):
    """The icon of its type (icon=False: where a row shows it already), the title (linked to url if given), the name
    small if the title is the purpose, then the code (its unique identifier unless given; "" for none), with `info` a
    chip that shows the location in brief. Not in the suggestions of location fields, where a click chooses the
    location. `mark`: what the title becomes (search words marked)."""
    code = location.unique_identifier if code is None else code
    title = format_html('<span class="loc-title">{}</span>', mark(location.title) if mark else location.title)
    parts = [format_html('<a href="{}">{}</a>', url, title) if url else title]
    if icon:
        parts.insert(0, type_icon(icon_name(location)))
    if subtitle and location.subtitle:
        parts.append(format_html('<span class="loc-name">{}</span>', location.subtitle))
    if code:
        parts.append(code_html(code, location=location if info else None))
    return format_html('<span class="loc-label{}">{}</span>', f" {classes}" if classes else "",
                       format_html_join(" ", "{}", ((part,) for part in parts)))


def option_html(location, above=None):
    """A location in an autocomplete's suggestions: its label, and below it where it is, the whole path from the top
    (`above`: the locations above it, paths(); else loaded here). Without links: a click chooses the location."""
    if above is None:
        above = paths([location])[location.pk]
    where = format_html('<span class="loc-where">{}</span>', path_html(above[-1], above=above[:-1], links=False)) \
        if above else ""
    return format_html('<span class="loc-option">{}{}</span>', label_html(location), where)


def paths(locations):
    """{pk: [the locations above it, from the top]} of these locations, in one query: by their code paths
    (locatable_identifier, HW.R3.a: HW and HW.R3), with their types for the icons."""
    from .models import Location

    prefixes = {location.pk: [location.locatable_identifier[:index] for index, char
                              in enumerate(location.locatable_identifier) if char == "."]
                for location in locations}
    found = {location.locatable_identifier: location for location in Location.objects.filter(
        locatable_identifier__in={prefix for chain in prefixes.values() for prefix in chain}).select_related("type")}
    return {pk: [found[prefix] for prefix in chain if prefix in found] for pk, chain in prefixes.items()}


def path_html(location, above=None, itself=True, links=True, below=None, mark=None):
    """Where it is: each location from the top, with the icon of its type, its title and its short name, between
    them ›; then the location itself, unless itself=False. `above`: the locations above it (paths()), else loaded
    here; `below`: leave out those down to this one (the page's own location, whose list this is); `mark` as in
    label_html."""
    if above is None:
        above = paths([location])[location.pk]
    if below is not None:
        pks = [step.pk for step in above]
        above = above[pks.index(below.pk) + 1:] if below.pk in pks else above
    steps = [*above, location] if itself else above
    return format_html('<span class="loc-path">{}</span>', format_html_join(
        mark_safe(' <span class="loc-path-sep" aria-hidden="true">›</span> '), "{}",
        ((label_html(step, code=step.short_name, subtitle=False, url=step.get_absolute_url() if links else None,
                     mark=mark),)
         for step in steps)))


def item_icon(item):
    """The icon of an item's kind: a serialized item box-star-stack, else (also for one no longer there) boxes."""
    from .models import Item

    return "box-star-stack" if item is not None and item.kind == Item.Kind.SERIALIZED else "boxes"


def item_html(item, url=None):
    """An item with the icon of its kind before its name, linked to url if given."""
    name = format_html('<a href="{}">{}</a>', url, item) if url else format_html("{}", item)
    return format_html('<span class="item-label">{} {}</span>', type_icon(item_icon(item)), name)


def unique_item_html(unique_item, url=None):
    """A unique item with its icon before its name (UniqueItem.name_html: item, own name, label ID), linked to url."""
    name = unique_item.name_html
    if url:
        name = format_html('<a href="{}">{}</a>', url, name)
    return format_html('<span class="item-label">{} {}</span>', type_icon("box-star"), name)



def object_html(obj, url=None):
    """A location, item or unique item, each with its icon (e.g. what a label ID belongs to); anything else as text."""
    from .models import Item, Location, UniqueItem

    if isinstance(obj, Location):
        return label_html(obj, url=url, subtitle=False)
    if isinstance(obj, Item):
        return item_html(obj, url=url)
    if isinstance(obj, UniqueItem):
        return unique_item_html(obj, url=url)
    return format_html('<a href="{}">{}</a>', url, obj) if url else format_html("{}", obj)
