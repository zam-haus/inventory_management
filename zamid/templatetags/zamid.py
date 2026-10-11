from django import template
from django.urls import reverse

from .. import core, lookup
from ..services import target_field_for
from ..targets import CLAIMABLE_FIELDS

register = template.Library()


@register.inclusion_tag("zamid/badge.html", takes_context=True)
def zam_badge(context, obj):
    """The active ZAM ID of `obj` with its QR code, or a form to attach a new label."""
    user = context.get("user")
    zid = lookup.active_id(obj)
    field = target_field_for(obj)
    can_claim = (zid is None and field in CLAIMABLE_FIELDS and not getattr(obj, "is_deleted", False)
                 and user is not None and user.has_perm("zamid.claim_zamid"))
    return {
        "zid": zid,
        "can_view": user is not None and user.has_perm("zamid.view_zamid"),
        "can_claim": can_claim,
        "claim_url": reverse("zamid_claim_for", args=[field, obj.pk]) if can_claim else None,
        "csrf_token": context.get("csrf_token"),
    }


@register.filter
def zam_display(code):
    return core.display(code) if code and core.is_valid(code) else code
