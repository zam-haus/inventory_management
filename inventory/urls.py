from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic.base import TemplateView

from . import attachment_views, unique_item_views, views
from .dissolve_views import DissolveLocationView
from .location_overview_views import LocationHistoryView, LocationOverviewUpdateView
from .quick_item_views import QuickItemCreateView, QuickItemDeleteView, QuickItemUpdateView
from .stock_change_views import StockChangeView


urlpatterns = [
    path("", views.index, name="index"),
    path("loc/dissolve/<int:pk>", DissolveLocationView.as_view(), name="location_dissolve"),
    path("loc/move-here/<int:pk>", views.LocationsMoveHereView.as_view(), name="locations_move_here"),
    path("loc/<int:pk>/overview/", LocationOverviewUpdateView.as_view(), name="location_overview_update"),
    path("loc/<int:pk>/history/", LocationHistoryView.as_view(), name="location_history"),
    path("loc/<int:pk>/quick-items/", QuickItemCreateView.as_view(), name="quick_item_create"),
    path("quick-items/<int:pk>/", QuickItemUpdateView.as_view(), name="quick_item_update"),
    path("quick-items/<int:pk>/delete/", QuickItemDeleteView.as_view(), name="quick_item_delete"),
    path("stock/<int:pk>/change/", StockChangeView.as_view(), name="stock_change"),
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
    path("item/<int:pk>/update", views.UpdateItemView.as_view(), name="update_item"),
    path("item/file/<int:pk>", views.ItemDocumentView.as_view(), name="item_file"),
    path("item/<int:pk>/photos/add", attachment_views.QuickPhotoView.as_view(), name="quick_item_photo"),
    path("item/<int:pk>/files/add", attachment_views.QuickFileView.as_view(), name="quick_item_file"),
    path("item/unique/<int:pk>/photos/add", attachment_views.QuickPhotoView.as_view(unique=True), name="quick_unique_item_photo"),
    path("item/unique/<int:pk>/files/add", attachment_views.QuickFileView.as_view(unique=True), name="quick_unique_item_file"),
    path("item/unique/<int:pk>/move", attachment_views.MoveUniqueItemView.as_view(), name="move_unique_item"),
    path("loc/lookup", attachment_views.location_lookup, name="location_lookup"),
    path("item/unique/create", unique_item_views.CreateUniqueItemView.as_view(), name="create_unique_item"),
    path("item/unique/<int:pk>", unique_item_views.DetailUniqueItemView.as_view(), name="view_unique_item"),
    path("item/unique/<int:pk>/update", unique_item_views.UpdateUniqueItemView.as_view(), name="update_unique_item"),
    path("item/unique/<int:pk>/dispose", unique_item_views.DisposeUniqueItemView.as_view(), name="dispose_unique_item"),
    path("item/unique/item-autocomplete/", unique_item_views.UniqueKindItemAutocomplete.as_view(),
         name="unique_kind_item_autocomplete"),
    path("item/unique/without-id-autocomplete/", unique_item_views.UniqueItemWithoutIdAutocomplete.as_view(),
         name="unique_item_without_id_autocomplete"),
    path("user-autocomplete/", unique_item_views.UserAutocomplete.as_view(), name="user_autocomplete"),
    path("category/<int:pk>.json", views.category_json, name="category_json"),
    path("parent_location_autocomplete", views.ParentLocationAutocompleteView.as_view(), name="parent_location_autocomplete"),

    path("id/", include("inventory.label_ids.urls")),
    path("robots.txt", TemplateView.as_view(template_name="inventory/robots.txt", content_type="text/plain")),
    path('location-autocomplete/', views.LocationAutocomplete.as_view(), name='location-autocomplete'),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
