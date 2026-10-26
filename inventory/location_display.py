"""
How locations are shown (docs/locations.md): what people call it first, its purpose, else its name
(the name small next to a purpose); its code after it, always alike: white monospace on muted grey (class loc-code,
inventory/locations.css). Template tags: {% load locations %}{% location_label location %}, {% location_code code %}.
"""
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext as _

# Icons of locations by what they are (LocationType.category, docs/icons.md); others, such as rooms, the pin.
CATEGORY_ICONS = {"storage_unit": "bookshelf", "container": "eurobox-open"}


def icon_name(location):
    """The icon of a location (inventory/icons.py), from its type's category; needs location.type."""
    return CATEGORY_ICONS.get(location.type.category, "geo-alt")


def code_html(code, classes="", location=None):
    """A location code (short name, unique or locatable identifier) as a chip. With the location, the chip shows
    it in brief when clicked (location_info.js), also inside a link, which the name follows."""
    classes = f" {classes}" if classes else ""
    if location is None:
        return format_html('<span class="loc-code{}">{}</span>', classes, code)
    return format_html('<span class="loc-code{}" data-location-info="{}" role="button" tabindex="0" title="{}">{}</span>',
                       classes, location.pk, _("Location in brief"), code)


def label_html(location, code=None, url=None, subtitle=True, classes="", info=False):
    """Title (linked to url if given), the name small if the title is the purpose, then the code (its unique
    identifier unless given; "" for none), with `info` a chip that shows the location in brief. Not in the
    suggestions of location fields, where a click chooses the location."""
    code = location.unique_identifier if code is None else code
    title = format_html('<span class="loc-title">{}</span>', location.title)
    parts = [format_html('<a href="{}">{}</a>', url, title) if url else title]
    if subtitle and location.subtitle:
        parts.append(format_html('<span class="loc-name">{}</span>', location.subtitle))
    if code:
        parts.append(code_html(code, location=location if info else None))
    return format_html('<span class="loc-label{}">{}</span>', f" {classes}" if classes else "",
                       format_html_join(" ", "{}", ((part,) for part in parts)))


def option_html(location):
    """A location in an autocomplete's suggestions: its label, and where it is, below."""
    parent = location.parent_location
    where = format_html('<span class="loc-where">{}</span>', parent.title) if parent else ""
    return format_html('<span class="loc-option">{}{}</span>', label_html(location), where)
