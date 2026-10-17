from django import template

from ..icons import icon as render_icon

register = template.Library()


@register.simple_tag
def icon(name, classes=""):
    """{% icon "camera" %}: an inline Bootstrap Icon (inventory/icons.py), hidden from screen readers."""
    return render_icon(name, classes)
