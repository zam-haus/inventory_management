"""URLconf for the resolver hosts i.zam.haus and id.zam.haus (see middleware.py)."""
from django.http import HttpResponse
from django.urls import path

from ..favicon import favicon
from . import resolver_views

urlpatterns = [
    path("", resolver_views.lookup, name="zamid_lookup"),
    path("robots.txt", lambda request: HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")),
    path("favicon.ico", favicon, {"name": "favicon.ico"}),
    path("favicon.svg", favicon, {"name": "favicon.svg"}),
    path("<str:raw>/", resolver_views.resolve),
    path("<str:raw>", resolver_views.resolve, name="zamid_resolve"),
]
