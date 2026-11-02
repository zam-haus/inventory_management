from django import template

from .. import icons
from ..icons import add_icon as render_add_icon
from ..icons import icon as render_icon

register = template.Library()


@register.simple_tag
def icon(name, classes=""):
    """{% icon "camera" %}: an inline Bootstrap Icon (inventory/icons.py), hidden from screen readers."""
    return render_icon(name, classes)


@register.simple_tag
def add_icon(name):
    """{% add_icon "camera" %}: what an "add" button adds, with a plus badge (inventory/icons.py)."""
    return render_add_icon(name)


@register.simple_tag
def type_icon(name):
    """{% type_icon "boxes" %}: the icon of a location's type or an item's kind before its name (icons.type_icon_names)."""
    return icons.type_icon(name)


@register.simple_tag
def type_icon_sprite(database=True):
    """Once on every page (base.html): the icons type_icon refers to; database=False on pages that must not need it."""
    return icons.type_icon_sprite(database)
