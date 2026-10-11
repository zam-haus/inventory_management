from django.shortcuts import redirect
from django.urls import reverse

from . import core, parsing
from .models import ZamId


def url_for_query(query):
    """Resolver URL when a search query is an issued ZAM ID (in any typed or scanned form)."""
    if not query:
        return None
    try:
        code = parsing.code_from_scan(query)
    except core.InvalidZamId:
        return None
    if not ZamId.objects.filter(pk=code).exists():
        return None
    return reverse("zamid_resolve", args=[code])


class ZamIdSearchMixin:
    """List views searched with ?q=<ZAM ID> jump straight to what the ID belongs to."""

    def get(self, request, *args, **kwargs):
        url = url_for_query(request.GET.get("q", "").strip())
        if url:
            return redirect(url)
        return super().get(request, *args, **kwargs)
