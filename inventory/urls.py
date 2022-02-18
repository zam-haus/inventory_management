from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('loc/<int:pk>/<str:unique_identifier>', views.view_location, name='view_location'),
    path('loc/<int:pk>/<str:unique_identifier>/update', views.update_location, name='update_location'),
    path('item/create', views.CreateItemView.as_view(), name='create_item'),

    path("item/", views.SearchableItemListView.as_view(), name='index_items'),
    path('item/<int:id>', views.view_item, name='view_item'),
    path('item/<int:id>/delete', views.delete_item, name='delete_item'),
    path('item/<int:id>/update', views.update_item, name='update_item'),
]
urlpatterns+= static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns+= static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
