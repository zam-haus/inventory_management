"""{% location_label location %} and {% location_code code %}: locations shown alike (location_display.py)."""
from django import template

from .. import location_display

register = template.Library()


@register.simple_tag
def location_label(location, code=None, url=None, subtitle=True, classes=""):
    """Title, the name small if the title is the purpose, the code (unique identifier unless given)."""
    return location_display.label_html(location, code=code, url=url, subtitle=subtitle, classes=classes)


@register.simple_tag
def location_code(code, classes=""):
    return location_display.code_html(code, classes)
