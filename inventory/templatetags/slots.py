from django import template
from django.utils.safestring import mark_safe

from .. import slots

register = template.Library()


@register.simple_tag(takes_context=True)
def slot(context, name):
    """Renders the templates registered for the slot `name` (inventory/slots.py) with the current context."""
    names = slots.templates(name)
    if not names:
        return ""
    engine = context.template.engine
    with context.push(slot_name=name):
        return mark_safe("".join(engine.get_template(template_name).render(context) for template_name in names))
