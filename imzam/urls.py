"""Application, admin and authentication routes."""
from django.contrib import admin
from django.urls import include, path
from inventory import pwa
from inventory.favicon import favicon
from inventory.views import ParentLocationAutocompleteView

urlpatterns = [
    path("admin/parent_location_autocomplete", ParentLocationAutocompleteView.as_view(), name="parent_location_autocomplete"),
    path("admin/", admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('oidc/', include('mozilla_django_oidc.urls')),
    path("favicon.ico", favicon, {"name": "favicon.ico"}),
    path("favicon.svg", favicon, {"name": "favicon.svg"}),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("print/", include("label_printing.urls")),
    path("", include("inventory.urls")),

]
