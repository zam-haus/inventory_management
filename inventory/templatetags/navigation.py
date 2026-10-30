from django import template

from ..help_views import help_link as render_help_link

register = template.Library()


@register.simple_tag(takes_context=True)
def in_section(context, *prefixes):
    """Whether the page belongs to the section of the navbar whose addresses start with one of `prefixes` (it is
    marked there as the current one)."""
    request = context.get("request")
    return bool(request) and any(request.path.startswith(prefix) for prefix in prefixes)


@register.simple_tag
def help_link(anchor, text=None):
    """{% help_link "zamid" %}: a quiet "More about this" link to that section of the help page."""
    return render_help_link(anchor, text)
