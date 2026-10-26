from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def in_section(context, *prefixes):
    """Whether the page belongs to the section of the navbar whose addresses start with one of `prefixes` (it is
    marked there as the current one)."""
    request = context.get("request")
    return bool(request) and any(request.path.startswith(prefix) for prefix in prefixes)
