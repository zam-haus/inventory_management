from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic.base import TemplateView

from . import views


urlpatterns = [
    path("", views.index, name="index"),
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
    path("item/create", views.CreateItemView.as_view(), name="create_item"),
    path("item/", views.SearchableItemListView.as_view(), name="index_items"),
    path("item/<int:pk>", views.DetailItemView.as_view(), name="view_item"),
    path("item/<int:pk>/annotate", views.AnnotateItemView.as_view(), name="annotate_item"),
    path("item/<int:pk>/delete", views.DeleteItemView.as_view(), name="delete_item"),
    # path('item/<int:pk>/move', views.move_item, name='move_item'),
    # path('item/<int:pk>/take', views.takee_item, name='take_item'),
    path("item/<int:pk>/update", views.UpdateItemView.as_view(), name="update_item"),
    path("category/<int:pk>.json", views.category_json, name="category_json"),
    # update for search functionality
    path('ajax/location-search/', views.search_location, name='location_search'),
    path("robots.txt", TemplateView.as_view(template_name="inventory/robots.txt", content_type="text/plain")),
    path('select2/', include('django_select2.urls')),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
