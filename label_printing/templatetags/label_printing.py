"""{% label_print_button object "location" %} in the actions of a page, {% label_print_dialog … %} once below."""
from django import template

from .. import dialog

register = template.Library()


def print_state(context, obj, subject_type):
    """(allowed, options, reason), worked out once per request and subject."""
    request, user = context.get("request"), context.get("user")
    allowed = bool(user and user.has_perm("label_printing.print_label"))
    if not allowed:
        return False, None, ""
    cache = getattr(request, "_label_print_states", None) if request else None
    if cache is None:
        cache = {}
        if request is not None:
            request._label_print_states = cache
    key = (subject_type, obj.pk)
    if key not in cache:
        options = dialog.options(subject_type, obj)
        cache[key] = (True, options, dialog.unavailable_reason(subject_type, options))
    return cache[key]


@register.inclusion_tag("label_printing/print_button.html", takes_context=True)
def label_print_button(context, obj, subject_type, classes="btn btn-info"):
    allowed, _options, reason = print_state(context, obj, subject_type)
    return {"user": context.get("user"), "request": context.get("request"), "object": obj,
            "subject_type": subject_type, "classes": classes, "allowed": allowed, "reason": reason}


@register.inclusion_tag("label_printing/print_dialog.html", takes_context=True)
def label_print_dialog(context, obj, subject_type):
    allowed, options, reason = print_state(context, obj, subject_type)
    form = None
    if allowed and not reason:
        form = dialog.PrintForm(subject_type=subject_type, obj=obj)
    return {"user": context.get("user"), "request": context.get("request"), "csrf_token": context.get("csrf_token"),
            "object": obj, "subject_type": subject_type, "form": form, "print_options": options, "modal": True,
            "options_id": f"label-print-options-{subject_type}",
            "print_title": dialog.title(subject_type, obj)}
