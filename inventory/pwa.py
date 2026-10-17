"""Installable web app: the manifest, the offline page and a service worker that shows it.

The service worker only steps in when a page cannot be loaded at all. Pages are never
served from a cache, so nobody sees outdated stock or another user's internal details.
"""
import hashlib
from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control

from .favicon import favicon_dir

# Bootstrap's bg-dark, the colour of the navbar.
THEME_COLOR = "#212529"


@cache_control(public=True, max_age=24 * 3600)
def manifest(request):
    directory = favicon_dir()
    name = _("ZAM inventory")
    if directory.endswith("/dev"):
        name += " (dev)"
    return JsonResponse({
        "id": "/",
        "name": name,
        "short_name": name,
        "start_url": reverse("index"),
        "scope": "/",
        "display": "standalone",
        # Installed apps stay upright (Android; iOS ignores it, see docs/installable-app.md).
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": THEME_COLOR,
        "icons": [
            {"src": static(f"{directory}/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static(f"{directory}/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static(f"{directory}/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }, content_type="application/manifest+json")


def offline_context():
    # The logo is inlined: while offline, nothing but the page itself can be loaded.
    return {"logo": Path(finders.find(f"{favicon_dir()}/favicon.svg")).read_text()}


def offline(request):
    return render(request, "inventory/pwa/offline.html", offline_context())


@cache_control(no_cache=True)
def service_worker(request):
    # The cache name follows the offline page, so browsers fetch the new page when it changes.
    page = render_to_string("inventory/pwa/offline.html", offline_context(), request)
    script = render_to_string("inventory/pwa/sw.js", {
        "cache": "offline-" + hashlib.sha256(page.encode()).hexdigest()[:12],
        "offline_url": reverse("offline"),
    })
    return HttpResponse(script, content_type="text/javascript")
