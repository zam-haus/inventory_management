"""{% location_label location %} and {% location_code code %}: locations shown alike (location_display.py)."""
from django import template

from .. import location_display

register = template.Library()


@register.simple_tag
def location_label(location, code=None, url=None, subtitle=True, classes="", info=True):
    """Title, the name small if the title is the purpose, the code (unique identifier unless given), which shows
    the location in brief (info=False: only the code)."""
    return location_display.label_html(location, code=code, url=url, subtitle=subtitle, classes=classes, info=info)


@register.simple_tag
def location_code(code, classes="", location=None):
    """A code as a chip; with the location, it shows it in brief."""
    return location_display.code_html(code, classes, location=location)


@register.filter
def icon_name(location):
    """The icon of a location's kind: {% icon location|icon_name %}."""
    return location_display.icon_name(location)
