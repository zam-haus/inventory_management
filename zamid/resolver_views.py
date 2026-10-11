"""
The resolver behind every printed QR code. i.zam.haus/<id>, id.zam.haus/<id>
and inv.zam.haus/id/<id> all run these views and answer identically; only
redirects into the inventory are absolute on the resolver hosts.

Kept free of inventory code so it can be split out later: targets only need
get_absolute_url() and, optionally, is_deleted.
"""
from contextlib import contextmanager

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import get_urlconf, reverse, set_urlconf
from django.views.decorators.http import require_safe

from . import core, parsing, throttle
from .models import ZamId


@contextmanager
def root_urlconf():
    """Reverse inventory URLs even while a request is served by the resolver URLconf."""
    previous = get_urlconf()
    set_urlconf(None)
    try:
        yield
    finally:
        set_urlconf(previous)


def inventory_base():
    return (getattr(settings, "ZAMID_INVENTORY_BASE", None) or settings.DEFAULT_DOMAIN).rstrip("/")


def inventory_url(request, build):
    """`build()` returns an inventory path; make it absolute when served on a resolver host."""
    with root_urlconf():
        path = build()
    if getattr(request, "zamid_resolver_host", False):
        return inventory_base() + path
    return path


def target_url(request, zid):
    if zid.url:
        return zid.url
    target = zid.target
    if target is None or zid.target_is_deleted:
        return None
    return inventory_url(request, target.get_absolute_url)


def _page(request, state, status, **context):
    return render(request, "zamid/resolver.html", {"state": state, **context}, status=status)


def _resolve(request, raw, *, from_lookup=False):
    if throttle.blocked(request):
        return _page(request, "throttled", 429)
    try:
        code = parsing.code_from_scan(raw)
    except core.InvalidZamId as e:
        throttle.hit(request)
        reason = e.args[0]
        suggestions = []
        if reason == "checksum":
            known = ZamId.objects.filter(pk__in=parsing.suggestions_for_scan(raw)).order_by("code")
            suggestions = [(zid.display, reverse("zamid_resolve", args=[zid.code])) for zid in known]
        return _page(request, reason, 404, q=raw, suggestions=suggestions)
    if from_lookup:
        return HttpResponseRedirect(reverse("zamid_resolve", args=[code]))

    zid = ZamId.objects.select_related("item", "location").filter(pk=code).first()
    if zid is None:
        throttle.hit(request)
        return _page(request, "unknown", 404, code=core.display(code))
    if zid.status == ZamId.Status.RESERVED:
        return HttpResponseRedirect(inventory_url(request, lambda: reverse("zamid_claim", args=[code])))
    url = target_url(request, zid)
    if zid.status == ZamId.Status.ASSIGNED and url:
        return HttpResponseRedirect(url)
    state = "retired" if zid.status == ZamId.Status.RETIRED else "deleted"
    return _page(request, state, 410, code=zid.display, target_url=url,
                 target_label=str(zid.target) if zid.target is not None and url else url)


@require_safe
def resolve(request, raw):
    return _resolve(request, raw)


@require_safe
def lookup(request):
    q = request.GET.get("q", "").strip()
    if not q:
        return _page(request, "lookup", 200)
    return _resolve(request, q, from_lookup=True)
