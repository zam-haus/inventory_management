"""{% location_label location %}, {% location_path location %} and {% location_code code %}: locations shown alike;
{% item_label item %}, {% unique_item_label unique_item %}: items and unique items with their icons
(location_display.py); {% zamid code %}: a label ID (label_ids/naming.py)."""
from django import template

from .. import location_display
from ..label_ids import naming

register = template.Library()


@register.simple_tag
def location_label(location, code=None, url=None, subtitle=True, classes="", info=True, icon=True):
    """The icon of its type, the title, the name small if the title is the purpose, the code (unique identifier
    unless given), which shows the location in brief (info=False: only the code)."""
    return location_display.label_html(location, code=code, url=url, subtitle=subtitle, classes=classes, info=info,
                                       icon=icon)


@register.simple_tag
def location_path(location, itself=True, links=True, paths=None):
    """Where it is: the locations above it (and itself), each with its icon and short name. `paths`: those above
    each of a list's locations (location_display.paths), else loaded for this one."""
    above = paths.get(location.pk) if paths else None
    return location_display.path_html(location, above=above, itself=itself, links=links)


@register.simple_tag
def item_label(item, url=None):
    return location_display.item_html(item, url=url)


@register.simple_tag
def unique_item_label(unique_item, url=None, icon=True):
    return location_display.unique_item_html(unique_item, url=url, icon=icon)


@register.simple_tag
def location_code(code, classes="", location=None):
    """A code as a chip; with the location, it shows it in brief."""
    return location_display.code_html(code, classes, location=location)


@register.filter
def icon_name(location):
    """The icon of a location's kind: {% icon location|icon_name %}."""
    return location_display.icon_name(location)


@register.filter
def category_icon(category):
    """The icon of the locations of a category: {% add_icon "container"|category_icon %}."""
    return location_display.category_icon_name(category)




@register.simple_tag
def object_label(obj, url=None):
    """A location, item or unique item with its icon."""
    return location_display.object_html(obj, url=url)


@register.simple_tag
def location_name(location):
    """In a sentence: the icon of its type and its title, without code ("width and depth from <icon> Regal 3")."""
    return location_display.label_html(location, code="", subtitle=False)



@register.filter
def item_icon(item):
    """The icon of an item's kind: {% type_icon item|item_icon %}, data for scripts."""
    return location_display.item_icon(item)


@register.simple_tag
def zamid(display):
    """A label ID (its display form, K7R-4XD) as everywhere: bold Roboto Mono, as on the label."""
    return naming.html(display)
