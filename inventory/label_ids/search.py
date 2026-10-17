from django.shortcuts import redirect

from ..models import LabelId, LabelIdAccess
from . import core, parsing
from .resolver_views import access_url


def url_for_query(request, query):
    """Resolver URL when a search query is an issued label ID (in any typed or scanned form); records a web form access."""
    if not query:
        return None
    try:
        code = parsing.code_from_scan(query)
    except core.InvalidLabelId:
        return None
    if not LabelId.objects.filter(pk=code).exists():
        return None
    return access_url(request, code, LabelIdAccess.Method.WEBFORM)


class LabelIdSearchMixin:
    """List views searched with ?q=<label ID> jump straight to what the ID belongs to."""

    def get(self, request, *args, **kwargs):
        url = url_for_query(request, request.GET.get("q", "").strip())
        if url:
            return redirect(url)
        return super().get(request, *args, **kwargs)
