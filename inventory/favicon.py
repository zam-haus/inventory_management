"""The site icon at the root paths browsers ask for, also on the resolver hosts (which serve no static files)."""
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse
from django.views.decorators.cache import cache_control

CONTENT_TYPES = {"favicon.ico": "image/x-icon", "favicon.svg": "image/svg+xml"}


def favicon_dir():
    """Static folder of the logo and icons: the magenta variant marks a dev system (DEBUG)."""
    return "inventory/favicon/dev" if settings.DEBUG else "inventory/favicon"


def favicon_context(request):
    """Context processor: lets every template link the logo and icons of this system."""
    return {"favicon_dir": favicon_dir()}


@cache_control(public=True, max_age=7 * 24 * 3600)
def favicon(request, name):
    path = finders.find(f"{favicon_dir()}/{name}")
    if name not in CONTENT_TYPES or not path:
        raise Http404
    # A few kilobytes: read at once instead of streaming an open file.
    return HttpResponse(Path(path).read_bytes(), content_type=CONTENT_TYPES[name])
