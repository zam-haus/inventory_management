"""{{ text|highlight:words }}: the search words marked in a text of a search result (docs/search.md)."""
import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()


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
