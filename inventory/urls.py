from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

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
    path("item/<int:pk>", views.view_item, name="view_item"),
    # path('item/<int:pk>/delete', views.delete_item, name='delete_item'),
    # path('item/<int:pk>/move', views.move_item, name='move_item'),
    # path('item/<int:pk>/take', views.takee_item, name='take_item'),
    path("item/<int:pk>/update", views.UpdateItemView.as_view(), name="update_item"),
]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
