from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.views.generic.base import TemplateView

from . import views
from .dissolve_views import DissolveLocationView
from .location_overview_views import LocationHistoryView, LocationOverviewUpdateView
from .quick_item_views import QuickItemCreateView, QuickItemDeleteView, QuickItemUpdateView


urlpatterns = [
    path("", views.index, name="index"),
    path("loc/dissolve/<int:pk>", DissolveLocationView.as_view(), name="location_dissolve"),
    path("loc/move-here/<int:pk>", views.LocationsMoveHereView.as_view(), name="locations_move_here"),
    path("loc/<int:pk>/overview/", LocationOverviewUpdateView.as_view(), name="location_overview_update"),
    path("loc/<int:pk>/history/", LocationHistoryView.as_view(), name="location_history"),
    path("loc/<int:pk>/quick-items/", QuickItemCreateView.as_view(), name="quick_item_create"),
    path("quick-items/<int:pk>/", QuickItemUpdateView.as_view(), name="quick_item_update"),
    path("quick-items/<int:pk>/delete/", QuickItemDeleteView.as_view(), name="quick_item_delete"),
    path(
        "loc/<int:pk>",
        views.DetailLocationView.as_view(),
        name="view_location2",
    ),
    path(
        "loc/move/<int:pk>",
        views.LocationMoveView.as_view(),
        name="location_move",
    ),
    path(
        "loc/<int:pk>/<str:unique_identifier>",
        views.DetailLocationView.as_view(),
        name="view_location",
    ),
    path(
        "loc/<int:pk>/<str:unique_identifier>/update",
        views.update_location,
        name="update_location",
    ),
    path("loc/", views.SearchableLocationListView.as_view(), name="index_locations"),
    path("inventory/print/", views.PrintableInventoryView.as_view(), name="print_inventory"),
    path("item/create", views.CreateItemView.as_view(), name="create_item"),
    path("item/", views.SearchableItemListView.as_view(), name="index_items"),
    path("item/<int:pk>", views.DetailItemView.as_view(), name="view_item"),
    path("item/<int:pk>/annotate", views.AnnotateItemView.as_view(), name="annotate_item"),
    path("item/<int:pk>/update", views.UpdateItemView.as_view(), name="update_item"),
    path("category/<int:pk>.json", views.category_json, name="category_json"),
    path("parent_location_autocomplete", views.ParentLocationAutocompleteView.as_view(), name="parent_location_autocomplete"),

    path("robots.txt", TemplateView.as_view(template_name="inventory/robots.txt", content_type="text/plain")),
    path('location-autocomplete/', views.LocationAutocomplete.as_view(), name='location-autocomplete'),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
