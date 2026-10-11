from django.contrib import messages
from django.utils.translation import gettext as _

from . import core, parsing, services


class ClaimOnAddMixin:
    """
    Admin add views opened with ?zamid=<code> (from the claim page) link the new
    object to that reserved ID right after it is saved.
    """

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        raw = request.GET.get("zamid")
        if change or not raw:
            return
        try:
            zid = services.claim(parsing.code_from_scan(raw), obj, request.user)
        except core.InvalidZamId:
            messages.error(request, _("%(code)s is not a valid ID.") % {"code": raw})
        except services.ZamIdError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("The ID %(code)s now belongs to %(target)s.") % {"code": zid.display, "target": obj})
