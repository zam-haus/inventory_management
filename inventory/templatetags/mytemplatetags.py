import markdown as markdown_lib
import nh3
from django import template
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

register = template.Library()

# Descriptions are public; everything else written in Markdown is removed.
MARKDOWN_TAGS = {
    "p", "br", "strong", "em", "a", "ul", "ol", "li", "code", "pre", "blockquote",
    "h3", "h4", "h5", "h6", "hr",
}


@register.simple_tag
def url_replace(request, field, value):
    d = request.GET.copy()
    d[field] = value
    return d.urlencode()

@register.simple_tag
def url_delete(request, field):
    d = request.GET.copy()
    del d[field]
    return d.urlencode()


def render_markdown(text):
    # nl2br keeps the line breaks of descriptions written before Markdown.
    html = markdown_lib.markdown(text or "", extensions=["nl2br", "sane_lists"])
    return nh3.clean(
        html, tags=MARKDOWN_TAGS, attributes={"a": {"href", "title"}},
        url_schemes={"http", "https", "mailto"}, link_rel="nofollow noopener noreferrer",
    )


@register.filter(is_safe=True)
def markdown(text):
    return mark_safe(render_markdown(text))


@register.filter
def markdown_plain(text):
    """The text of rendered Markdown, for short previews."""
    return " ".join(strip_tags(render_markdown(text)).split())


@register.inclusion_tag("inventory/usage_level.html")
def usage_level(level, long=False):
    """
    The briefing requirement as a coloured symbol; the short form names the colour
    and explains it on hover, the long form shows the explanation.
    """
    from ..models import USAGE_LEVEL_DESCRIPTIONS, USAGE_LEVEL_SYMBOLS, UsageLevel

    if not level:
        return {"level": None}
    return {"level": level, "label": UsageLevel(level).label, "symbol": USAGE_LEVEL_SYMBOLS[level],
            "description": USAGE_LEVEL_DESCRIPTIONS[level], "long": long}
