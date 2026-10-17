"""Inventory-side routes, mounted at /id/. /id/<id> is the same resolver as i.zam.haus/<id>."""
from django.urls import path

from . import resolver_views, views

urlpatterns = [
    path("", resolver_views.lookup, name="label_id_lookup"),
    path("item-autocomplete/", views.ItemAutocomplete.as_view(), name="label_id_item_autocomplete"),
    path("<str:code>/info/", views.InfoView.as_view(), name="label_id_info"),
    path("<str:code>/claim/", views.ClaimView.as_view(), name="label_id_claim"),
    path("<str:code>/qr.svg", views.qr_svg, name="label_id_qr_svg"),
    path("<str:code>/qr.png", views.qr_png, name="label_id_qr_png"),
    path("<str:code>/label.png", views.LabelView.as_view(), name="label_id_label"),
    path("<str:raw>/", resolver_views.resolve),
    path("<str:raw>", resolver_views.resolve, name="label_id_resolve"),
]
