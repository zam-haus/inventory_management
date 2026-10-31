"""
The last accesses of a label ID by label scan or web form. Clicking links inside
the inventory is not an access.

Label scans arrive on the resolver hosts, where the inventory login is unknown
(its cookie belongs to another domain). The resolver therefore sends them, and
web form entries, to /id/<code>?via=<method> on the inventory host first, which
records the access with the logged-in user and then resolves as usual. The
marker is not protected: such URLs only exist between these redirects.

A label link shared in a chat is fetched by the chat's link preview bot: it is resolved as usual but not recorded,
or it would push the real scans out of the few kept.
"""
from django.conf import settings

from ..link_preview import is_link_preview
from ..models import LabelIdAccess


def keep():
    return getattr(settings, "LABEL_ID_ACCESS_KEEP", 5)


def method_from(request):
    """The access method a GET request was marked with by the resolver or the search, or None (also for link
    preview bots)."""
    method = request.GET.get("via")
    if request.method != "GET" or method not in LabelIdAccess.Method.values or is_link_preview(request):
        return None
    return method


def record(request, lid, method):
    LabelIdAccess.objects.create(label=lid, user=request.user if request.user.is_authenticated else None, method=method,
                               local_network=getattr(request, "from_local_network", False))  # set by imzam.local_network
    stale = list(LabelIdAccess.objects.filter(label=lid).values_list("pk", flat=True)[keep():])
    if stale:
        LabelIdAccess.objects.filter(pk__in=stale).delete()


def latest(lid):
    return list(lid.accesses.select_related("user")[:keep()])
