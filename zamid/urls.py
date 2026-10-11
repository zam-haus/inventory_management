"""Inventory-side routes, mounted at /id/. /id/<id> is the same resolver as i.zam.haus/<id>."""
from django.urls import path

from . import resolver_views, views

urlpatterns = [
    path("", resolver_views.lookup, name="zamid_lookup"),
    path("claim-for/<str:kind>/<int:pk>/", views.ClaimForView.as_view(), name="zamid_claim_for"),
    path("item-autocomplete/", views.ItemAutocomplete.as_view(), name="zamid_item_autocomplete"),
    path("<str:code>/info/", views.InfoView.as_view(), name="zamid_info"),
    path("<str:code>/claim/", views.ClaimView.as_view(), name="zamid_claim"),
    path("<str:code>/qr.svg", views.qr_svg, name="zamid_qr_svg"),
    path("<str:code>/qr.png", views.qr_png, name="zamid_qr_png"),
    path("<str:code>/label.png", views.LabelView.as_view(), name="zamid_label"),
    path("<str:raw>/", resolver_views.resolve),
    path("<str:raw>", resolver_views.resolve, name="zamid_resolve"),
]
