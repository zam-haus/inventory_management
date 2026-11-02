import re

from django.conf import settings
from django.conf.urls.static import static
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.urls import include, path, re_path
from django.views.static import serve
from django.views.generic.base import TemplateView

from . import attachment_views, unique_item_views, views
from .dissolve_views import DissolveLocationView
from .help_views import HelpView
from .problem_reports import ProblemReportView
from .location_overview_views import (
    LocationDescriptionUpdateView, LocationDimensionsUpdateView, LocationOverviewUpdateView, LocationPurposeUpdateView,
    LocationResponsibilityUpdateView,
)
from .numbered_location_views import (
    ContainerActivateView, ContainerCreateView, NumberedLocationCreateView, SublocationAddView, SublocationPurposeView,
)
from .quick_item_views import QuickItemCreateView, QuickItemDeleteView, QuickItemPhotoView, QuickItemUpdateView
from .stock_change_views import StockChangeView


urlpatterns = [
    path("", views.SearchView.as_view(), name="index"),
    path("location/dissolve/<int:pk>", DissolveLocationView.as_view(), name="location_dissolve"),
    path("location/move-here/<int:pk>", views.LocationsMoveHereView.as_view(), name="locations_move_here"),
    path("location/<int:pk>/rows/<slug:part>/", views.location_rows, name="location_rows"),
    path("location/<int:pk>/overview/", LocationOverviewUpdateView.as_view(), name="location_overview_update"),
    path("location/<int:pk>/purpose/", LocationPurposeUpdateView.as_view(), name="location_purpose_update"),
    path("location/<int:pk>/responsibility/", LocationResponsibilityUpdateView.as_view(),
         name="location_responsibility_update"),
    path("location/<int:pk>/description/", LocationDescriptionUpdateView.as_view(), name="location_description_update"),
    path("location/<int:pk>/dimensions/", LocationDimensionsUpdateView.as_view(), name="location_dimensions_update"),
    path("location/<int:pk>/new-shelf/", NumberedLocationCreateView.as_view(), name="numbered_location_create"),
    path("location/<int:pk>/new-container/", ContainerCreateView.as_view(), name="container_create"),
    path("location/<int:pk>/activate/", ContainerActivateView.as_view(), name="container_activate"),
    path("location/<int:pk>/add-sublocations/", SublocationAddView.as_view(), name="sublocation_add"),
    path("location/<int:pk>/sublocation-purposes/", SublocationPurposeView.as_view(), name="sublocation_purposes"),
    path("location/<int:pk>/quick-items/", QuickItemCreateView.as_view(), name="quick_item_create"),
    path("quick-items/<int:pk>/", QuickItemUpdateView.as_view(), name="quick_item_update"),
    path("quick-items/<int:pk>/delete/", QuickItemDeleteView.as_view(), name="quick_item_delete"),
    path("quick-items/<int:pk>/photo/", QuickItemPhotoView.as_view(), name="quick_item_set_photo"),
    path("stock/<int:pk>/change/", StockChangeView.as_view(), name="stock_change"),
    path("location/move/<int:pk>", views.LocationMoveView.as_view(), name="location_move"),
    path("location/<int:pk>/info/", views.LocationInfoView.as_view(), name="location_info"),
    path("location/", views.LocationTreeView.as_view(), name="index_locations"),
    path("location/structure/", views.StructureOverviewView.as_view(), name="structure_overview"),
    path("location/lookup", attachment_views.location_lookup, name="location_lookup"),
    # A location's page by its code (docs/locations.md); after the fixed paths above (Location._validate_codes keeps
    # codes from equalling them).
    path("location/<str:code>", views.DetailLocationView.as_view(), name="view_location"),
    # The earlier addresses, kept for what links to them: every label printed before has /loc/<pk>/<code> in its QR
    # code. Each goes on to the new one.
    path("loc/<int:pk>/<str:code>", views.legacy_location, name="view_location_legacy"),
    path("loc/<int:pk>", views.legacy_location, name="view_location_legacy_pk"),
    path("loc/", views.LegacyRedirectView.as_view(pattern_name="index_locations"), name="legacy_index_locations"),
    path("loc/structure/", views.LegacyRedirectView.as_view(pattern_name="structure_overview"),
         name="legacy_structure_overview"),
    path("inventory/print/", views.PrintableInventoryView.as_view(), name="print_inventory"),
    path("item/create", views.CreateItemView.as_view(), name="create_item"),
    path("item/", views.ItemTreeView.as_view(), name="index_items"),
    path("item/rows/", views.item_tree_rows, name="item_tree_rows"),
    path("item/<int:pk>", views.DetailItemView.as_view(), name="view_item"),
    path("item/<int:pk>/update", views.UpdateItemView.as_view(), name="update_item"),
    path("item/<int:pk>/serialize", unique_item_views.SerializeItemView.as_view(), name="serialize_item"),
    path("item/file/<int:pk>", views.ItemDocumentView.as_view(), name="item_file"),
    path("item/<int:pk>/photos/add", attachment_views.QuickPhotoView.as_view(), name="quick_item_photo"),
    path("item/<int:pk>/files/add", attachment_views.QuickFileView.as_view(), name="quick_item_file"),
    path("item/unique/<int:pk>/photos/add", attachment_views.QuickPhotoView.as_view(unique=True), name="quick_unique_item_photo"),
    path("item/unique/<int:pk>/files/add", attachment_views.QuickFileView.as_view(unique=True), name="quick_unique_item_file"),
    path("item/unique/<int:pk>/move", attachment_views.MoveUniqueItemView.as_view(), name="move_unique_item"),
    path("item/unique/create", unique_item_views.CreateUniqueItemView.as_view(), name="create_unique_item"),
    path("item/unique/create/item", unique_item_views.UniqueItemItemStepView.as_view(), name="create_unique_item_item"),
    path("item/unique/<int:pk>", unique_item_views.DetailUniqueItemView.as_view(), name="view_unique_item"),
    path("item/unique/<int:pk>/update", unique_item_views.UpdateUniqueItemView.as_view(), name="update_unique_item"),
    path("item/unique/<int:pk>/notes", unique_item_views.UniqueItemNotesUpdateView.as_view(), name="unique_item_notes_update"),
    path("item/unique/<int:pk>/responsibility", unique_item_views.UniqueItemResponsibilityUpdateView.as_view(),
         name="unique_item_responsibility_update"),
    path("item/unique/<int:pk>/dispose", unique_item_views.DisposeUniqueItemView.as_view(), name="dispose_unique_item"),
    path("item/serialized-autocomplete/", unique_item_views.SerializedItemAutocomplete.as_view(),
         name="serialized_item_autocomplete"),
    path("item/unique/without-id-autocomplete/", unique_item_views.UniqueItemWithoutIdAutocomplete.as_view(),
         name="unique_item_without_id_autocomplete"),
    path("user-autocomplete/", unique_item_views.UserAutocomplete.as_view(), name="user_autocomplete"),
    path("category/<int:pk>.json", views.category_json, name="category_json"),
    path("category/<int:pk>/", views.CategoryView.as_view(), name="view_category"),
    path("parent_location_autocomplete", views.ParentLocationAutocompleteView.as_view(), name="parent_location_autocomplete"),

    path("id/", include("inventory.label_ids.urls")),
    path("help/", HelpView.as_view(), name="help"),
    path("problem/", ProblemReportView.as_view(), name="problem_report"),
    path("robots.txt", TemplateView.as_view(template_name="inventory/robots.txt", content_type="text/plain")),
    path('location-autocomplete/', views.LocationAutocomplete.as_view(), name='location-autocomplete'),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


def media(request, path):
    """Media files in development as nginx serves them (nginx.conf): attached documents only through the
    app, which checks internal ones. Missing ones come from MEDIA_REMOTE_URL (remote_media.py)."""
    if path.startswith("documents/"):
        raise PermissionDenied
    default_storage.exists(path)
    return serve(request, path, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    urlpatterns += [re_path(rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$", media)]
