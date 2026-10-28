from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from . import plans
from inventory.admin import LocationTypeAdmin

from .models import (BackgroundLayer, FloorPlan, LocationShape, LocationTypeMap, SurveyedPoint,
                     UniqueItemPosition)


# Plain ModelAdmins: GeoDjango's map widgets load map tiles from third parties. Positions and plans are placed on
# the site's own map (/map/); the admin shows them as text.

@admin.register(FloorPlan)
class FloorPlanAdmin(admin.ModelAdmin):
    list_display = ("__str__", "level", "location", "active", "shown", "placed", "residual_m", "created")
    list_editable = ("active", "shown")
    list_filter = ("active", "shown", "level")
    search_fields = ("name", "location__unique_identifier", "location__name")
    autocomplete_fields = ("location",)
    readonly_fields = ("image", "image_width", "image_height", "corners", "outline", "residual_m", "created",
                       "created_by")
    fields = ("level", "location", "name", "notes", "source", "page", "dpi", "crop", "transparent", "active", "shown", "opacity",
              "control_points", "affine",
              "image", "image_width", "image_height", "corners", "outline", "residual_m", "created", "created_by")

    @admin.display(boolean=True, description=_("placed"))
    def placed(self, plan):
        return plan.is_placed

    def save_model(self, request, plan, form, change):
        if not change:
            plan.created_by = request.user
        rendered = not change or bool({"source", "page", "dpi", "crop", "transparent"} & set(form.changed_data))
        try:
            plans.save(plan, rendered=rendered)
        except plans.PlanError as error:
            plan.save()
            messages.error(request, str(error))


@admin.register(LocationShape)
class LocationShapeAdmin(admin.ModelAdmin):
    list_display = ("location", "kind", "parts_stacked", "width_cm", "depth_cm")
    list_filter = ("kind", "parts_stacked")
    search_fields = ("location__unique_identifier", "location__name")
    autocomplete_fields = ("location",)
    readonly_fields = ("geometry",)
    fields = ("location", "kind", "geometry", "rotation", "width_cm", "depth_cm", "parts_stacked")


# The map settings of a location type, grouped; a rectangle's default size on its line.
LOCATION_TYPE_MAP_FIELDSETS = (
    (_("Shapes"), {"fields": ("placeable", "as_point", ("as_rectangle", "default_width_cm", "default_depth_cm"),
                             "as_area")}),
    (_("Look"), {"fields": (("color", "fill_color"), ("fill_opacity", "line_width"), "style_options")}),
    (pgettext_lazy("map", "Label"), {"fields": ("label", "label_min_zoom", ("label_size", "label_color", "label_bold"))}),
)


class LocationTypeMapInline(admin.StackedInline):
    """On the location type's admin page: whether and how its locations are placed and shown on the map."""
    model = LocationTypeMap
    can_delete = False
    verbose_name_plural = _("map")
    fieldsets = LOCATION_TYPE_MAP_FIELDSETS


LocationTypeAdmin.inlines = [*LocationTypeAdmin.inlines, LocationTypeMapInline]


@admin.register(LocationTypeMap)
class LocationTypeMapAdmin(admin.ModelAdmin):
    """All location types at a glance: which are placed on the map."""
    list_display = ("type", "placeable", "as_point", "as_rectangle", "default_width_cm", "default_depth_cm", "as_area",
                    "label")
    list_editable = ("placeable", "as_point", "as_rectangle", "default_width_cm", "default_depth_cm", "as_area",
                     "label")
    list_filter = ("placeable",)
    fieldsets = ((None, {"fields": ("type",)}), *LOCATION_TYPE_MAP_FIELDSETS)


@admin.register(UniqueItemPosition)
class UniqueItemPositionAdmin(admin.ModelAdmin):
    list_display = ("unique_item", "point")
    autocomplete_fields = ("unique_item",)
    readonly_fields = ("point",)

    def has_add_permission(self, request):
        return False  # placed on the map


@admin.register(BackgroundLayer)
class BackgroundLayerAdmin(admin.ModelAdmin):
    """Which background maps the maps offer, from which tile servers, and which one they show first."""
    list_display = ("name", "active", "is_default", "position", "max_zoom", "url")
    list_editable = ("active", "position")
    list_display_links = ("name",)
    fields = ("name", "url", "attribution", "max_zoom", "active", "is_default", "position")


@admin.register(SurveyedPoint)
class SurveyedPointAdmin(admin.ModelAdmin):
    """Places with known coordinates, offered when placing plans."""
    list_display = ("name", "latitude", "longitude", "active", "position")
    list_editable = ("active", "position")
    fields = ("name", "latitude", "longitude", "active", "position")
