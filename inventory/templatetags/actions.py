"""Actions that are not available stay visible to logged-in users: a disabled button says why.

Guests do not see actions they lack the permission for. Technical reasons that a
guest can solve (no JavaScript, no camera) are explained to everyone; those
buttons are rendered by their templates and enabled by scripts (actions.js)."""
from itertools import count

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _

register = template.Library()
_ids = count(1)


@register.simple_tag(takes_context=True)
def disabled_action(context, content, name="", reason="", classes="btn btn-secondary", label=""):
    """A visible but disabled button; hovering, focusing or tapping it shows `reason`.

    Without a reason, it says the user lacks the permission. `content` is what the button
    shows (text or an icon), `label` a short text after it, `name` what screen readers
    announce (default: label, else content).
    Renders nothing for guests. Pass the classes of the usable button: disabled, it shows
    only the outline (actions.css).
    """
    user = context.get("user")
    if not (user and user.is_authenticated):
        return ""
    reason = reason or _("Your account is not allowed to do this. Ask an inventory admin for the permission.")
    if label:
        content = format_html('{} <span class="action-label">{}</span>', content, label)
        name = name or label
    reason_id = f"disabled-action-{next(_ids)}"
    return format_html(
        '<span class="disabled-action" tabindex="0" role="button" aria-disabled="true" aria-label="{}"'
        ' aria-describedby="{}" data-bs-toggle="tooltip" title="{}">'
        '<button class="{}" type="button" disabled aria-hidden="true">{}</button>'
        '<span id="{}" class="visually-hidden">{}</span></span>',
        name or content, reason_id, reason, classes, content, reason_id, reason,
    )
