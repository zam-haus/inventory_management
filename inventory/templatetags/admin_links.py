from django import template

from .. import admin_links

register = template.Library()


@register.simple_tag(takes_context=True)
def admin_page_url(context):
    """{% admin_page_url %}: the admin page that belongs to the page shown (inventory/admin_links.py)."""
    return admin_links.admin_page_url(context)
