from django.urls import path, register_converter

from . import views
from .levels import label


class LevelConverter:
    """Level numbers with their sign, as in the codes: /map/-1/, /map/+0/."""
    regex = r"[+-]\d+"

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return label(int(value))


register_converter(LevelConverter, "level")
app_name = "maps"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("<level:number>/", views.map_view, name="level"),
    path("level/<level:number>/data/", views.level_data, name="level_data"),
    path("level/<level:number>/unplaced/", views.unplaced, name="unplaced"),
    path("place/", views.place_context, name="place_context"),
    path("at/", views.area_at, name="area_at"),
    path("loc/<int:pk>/", views.LocationShapeView.as_view(), name="location_shape"),
    path("item/<int:pk>/", views.ItemPositionView.as_view(), name="item_position"),
    path("plans/", views.PlansView.as_view(), name="plans"),
    path("plans/<int:pk>/", views.PlanAlignView.as_view(), name="plan_align"),
    path("plans/<int:pk>/image", views.plan_image, name="plan_image"),
    path("plans/<int:pk>/tile/<int:index>", views.plan_tile, name="plan_tile"),
    path("plans/<int:pk>/source", views.plan_source, name="plan_source"),
]
