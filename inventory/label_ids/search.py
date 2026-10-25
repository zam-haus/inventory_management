from django.shortcuts import redirect
from django.urls import reverse

from .. import codes
from ..models import LabelIdAccess
from .resolver_views import access_url


def url_for_query(request, query, *, location_codes=True):
    """Where a search query leads when it is a code (codes.resolve_code), else None: a label ID through the
    resolver (recording a web form access), a location's code to its page, a reserved container's to its
    activation. Without `location_codes`, codes of locations (short words such as LAS) stay search text."""
    if not query:
        return None
    found = codes.resolve_code(query)
    if found.kind == codes.LABEL_ID:
        return access_url(request, found.code, LabelIdAccess.Method.WEBFORM)
    if not location_codes and "/" not in query:  # a scanned label URL is a code anyway
        return None
    if found.kind == codes.LOCATION:
        return found.location.get_absolute_url()
    if found.kind == codes.RESERVED:
        return reverse("container_activate", args=[found.location.pk])
    return None


class LabelIdSearchMixin:
    """List views searched with ?q=<code> jump straight to what it belongs to (url_for_query)."""
    location_codes = True

    def get(self, request, *args, **kwargs):
        url = url_for_query(request, request.GET.get("q", "").strip(), location_codes=self.location_codes)
        if url:
            return redirect(url)
        return super().get(request, *args, **kwargs)
