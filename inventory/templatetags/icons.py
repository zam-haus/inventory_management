from django import template

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
