"""
The resolver behind every printed QR code. i.zam.haus/<id>, id.zam.haus/<id>
and inventar.zam.haus/id/<id> all run these views and answer identically; only
redirects into the inventory are absolute on the resolver hosts.

Kept free of inventory code so it can be split out later: targets only need
get_absolute_url() and, optionally, is_deleted. The one exception: a location's code comes
first (location labels hold HTTPS://I.ZAM.HAUS/<code>).
"""
from contextlib import contextmanager
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import get_urlconf, reverse, set_urlconf
from django.views.decorators.http import require_safe

from ..location_lookup import locations_by_code
from ..models import LabelId, LabelIdAccess
from . import access, core, parsing, throttle
from .targets import RELATED_TARGETS


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
    return (getattr(settings, "LABEL_ID_INVENTORY_BASE", None) or settings.DEFAULT_URL).rstrip("/")


def inventory_url(request, build):
    """`build()` returns an inventory path; make it absolute when served on a resolver host."""
    with root_urlconf():
        path = build()
    if getattr(request, "label_id_resolver_host", False):
        return inventory_base() + path
    return path


# Arguments that go on to the target: loc, the location an item label is for (its number). The label holds the
# location's code after the ID (resolve_at); between the inventory's own hops it travels as ?loc=.
FORWARDED = ("loc",)


def forwarded(request):
    found = {name: request.GET[name] for name in FORWARDED if request.GET.get(name, "").isdigit()}
    return {**found, **getattr(request, "label_id_forwarded", {})}


def with_forwarded(request, url):
    """An inventory URL with the scan's forwarded arguments."""
    extra = forwarded(request)
    return f"{url}{'&' if '?' in url else '?'}{urlencode(extra)}" if extra else url


def access_url(request, code, method):
    """The inventory's /id/<code>, which records this access before resolving (see access.py)."""
    url = inventory_url(request, lambda: reverse("label_id_resolve", args=[code]))
    return f"{url}?{urlencode({'via': method, **forwarded(request)})}"


def target_url(request, lid):
    if lid.url:
        return lid.url
    target = lid.target
    if target is None or lid.target_is_deleted:
        return None
    return inventory_url(request, target.get_absolute_url)


def _page(request, state, status, **context):
    return render(request, "inventory/label_id/resolver.html", {"state": state, **context}, status=status)


def _location(request, raw):
    """For a location's code (or former code, in any case; codes differ in more than that): its page."""
    found = locations_by_code(parsing.strip_url(raw))
    if len(found) == 1:
        return HttpResponseRedirect(inventory_url(request, found[0].get_absolute_url))
    return None


def _resolve(request, raw, *, from_lookup=False):
    """`raw` from the URL path, or from the lookup form if `from_lookup`."""
    if throttle.blocked(request):
        return _page(request, "throttled", 429)
    # Location codes first; label IDs that equal one are never issued (services.generate_batch).
    if response := _location(request, raw):
        return response
    try:
        code = parsing.code_from_scan(raw)
    except core.InvalidLabelId as e:
        throttle.hit(request)
        reason = e.args[0]
        suggestions = []
        if reason == "checksum":
            known = LabelId.objects.filter(pk__in=parsing.suggestions_for_scan(raw)).order_by("code")
            suggestions = [(lid.display, reverse("label_id_resolve", args=[lid.code])) for lid in known]
        return _page(request, reason, 404, q=raw, suggestions=suggestions)
    if from_lookup:
        return HttpResponseRedirect(access_url(request, code, LabelIdAccess.Method.WEBFORM))

    lid = LabelId.objects.select_related(*RELATED_TARGETS).filter(pk=code).first()
    if lid is None:
        throttle.hit(request)
        return _page(request, "unknown", 404, code=core.display(code))
    # A label's QR code holds exactly the canonical code; anything else was typed or linked.
    if getattr(request, "label_id_resolver_host", False) and raw == code:
        return HttpResponseRedirect(access_url(request, code, LabelIdAccess.Method.LABEL_SCAN))
    if method := access.method_from(request):
        access.record(request, lid, method)
    if lid.status == LabelId.Status.RESERVED:
        return HttpResponseRedirect(inventory_url(request, lambda: reverse("label_id_claim", args=[code])))
    url = target_url(request, lid)
    if lid.status == LabelId.Status.ASSIGNED and url:
        # Arguments only go on to the inventory's pages, not to URLs elsewhere
        return HttpResponseRedirect(url if lid.url else with_forwarded(request, url))
    if "via" in request.GET:  # show the page under its plain URL, so reloading it is no further access
        return HttpResponseRedirect(request.path)
    state = "retired" if lid.status == LabelId.Status.RETIRED else "deleted"
    return _page(request, state, 410, code=lid.display, target_url=url,
                 target_label=str(lid.target) if lid.target is not None and url else url)


@require_safe
def resolve(request, raw):
    return _resolve(request, raw)


@require_safe
def resolve_at(request, raw, at):
    """An item label: the item's ID, then the code of the location it is stored at (uppercase, so the QR code
    stays alphanumeric). The location goes on to the item's page; one that is unknown is left out."""
    found = locations_by_code(at.strip("/"))
    if len(found) == 1:
        request.label_id_forwarded = {"loc": str(found[0].pk)}
    return _resolve(request, raw)


@require_safe
def lookup(request):
    q = request.GET.get("q", "").strip()
    if not q:
        return _page(request, "lookup", 200)
    return _resolve(request, q, from_lookup=True)
