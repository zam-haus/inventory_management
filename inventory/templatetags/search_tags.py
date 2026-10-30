"""For result rows (results/entries.html, docs/search.md): {{ text|highlight:words }} marks the search words in a
text; {% result_icon name %} shows an icon of the sprite that {% result_icon_sprite %} draws once per page."""
import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from .. import icons
from ..search.render import ICONS

register = template.Library()


@register.simple_tag
def result_icon(name):
    return icons.use(name, "result-icon", f"bi bi-{name}")


@register.simple_tag
def result_icon_sprite():
    return icons.sprite(ICONS, "result-icon", "result-sprite")


@register.simple_tag(takes_context=True)
def result_rows(context):
    """Marks the page as one with result rows (or one that will get them while typing): base.html then adds what
    they need once, at its end (result_rows_used)."""
    request = context.get("request")
    if request is not None:
        request.result_rows = True
    return ""


@register.simple_tag(takes_context=True)
def result_rows_used(context):
    return getattr(context.get("request"), "result_rows", False)


@register.filter
def highlight(text, words):
    """The text escaped, each occurrence of a word (ignoring case) in <mark>."""
    text = "" if text is None else str(text)
    words = sorted({word for word in words or () if word}, key=len, reverse=True)
    if not words:
        return escape(text)
    pattern = re.compile("|".join(re.escape(word) for word in words), re.IGNORECASE)
    parts, end = [], 0
    for match in pattern.finditer(text):
        parts += [escape(text[end:match.start()]), format_html("<mark>{}</mark>", match.group())]
        end = match.end()
    parts.append(escape(text[end:]))
    return mark_safe("".join(parts))
