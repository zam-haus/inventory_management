"""Application, admin and authentication routes."""
from django.contrib import admin
from django.urls import include, path
from inventory.views import ParentLocationAutocompleteView

urlpatterns = [
    path("admin/parent_location_autocomplete", ParentLocationAutocompleteView.as_view(), name="parent_location_autocomplete"),
    path("admin/", admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('oidc/', include('mozilla_django_oidc.urls')),
    path("", include("inventory.urls")),

]
