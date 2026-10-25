"""
How locations are shown (docs/locations.md): what people call it first, its purpose, else its name
(the name small next to a purpose); its code after it, always alike: white monospace on muted grey (class loc-code,
inventory/locations.css). Template tags: {% load locations %}{% location_label location %}, {% location_code code %}.
"""
from django.utils.html import format_html, format_html_join


def code_html(code, classes=""):
    """A location code (short name, unique or locatable identifier) as a chip."""
    return format_html('<span class="loc-code{}">{}</span>', f" {classes}" if classes else "", code)


def label_html(location, code=None, url=None, subtitle=True, classes=""):
    """Title (linked to url if given), the name small if the title is the purpose, then the code (its unique
    identifier unless given; "" for none)."""
    code = location.unique_identifier if code is None else code
    title = format_html('<span class="loc-title">{}</span>', location.title)
    parts = [format_html('<a href="{}">{}</a>', url, title) if url else title]
    if subtitle and location.subtitle:
        parts.append(format_html('<span class="loc-name">{}</span>', location.subtitle))
    if code:
        parts.append(code_html(code))
    return format_html('<span class="loc-label{}">{}</span>', f" {classes}" if classes else "",
                       format_html_join(" ", "{}", ((part,) for part in parts)))


def option_html(location):
    """A location in an autocomplete's suggestions: its label, and where it is, below."""
    parent = location.parent_location
    where = format_html('<span class="loc-where">{}</span>', parent.title) if parent else ""
    return format_html('<span class="loc-option">{}{}</span>', label_html(location), where)
