from django.db import migrations

# The look of the location types in use at ZAM, by name. Only rooms and areas are tinted; their parts are outlines
# only, so that at any place at most two tints lie on top of each other (a room and an area reaching into it).
LOOKS = {
    "Haus+Ebene": {"color": "#334155", "fill_color": "", "fill_opacity": 0, "line_width": 3},
    "Raum": {"color": "#2563eb", "fill_color": "#bfdbfe", "fill_opacity": 0.22, "line_width": 2,
             "label_min_zoom": 18, "label_bold": True},
    "Teilraum": {"color": "#2563eb", "fill_color": "", "fill_opacity": 0, "line_width": 1.25,
                 "style_options": {"dashArray": "5 3"}, "label_min_zoom": 19},
    "Bereich": {"color": "#d97706", "fill_color": "#fde68a", "fill_opacity": 0.25, "line_width": 2,
                "style_options": {"dashArray": "8 4"}, "label_min_zoom": 18, "label_bold": True},
    "Teilbereich": {"color": "#d97706", "fill_color": "", "fill_opacity": 0, "line_width": 1.25,
                    "style_options": {"dashArray": "2 3"}, "label_min_zoom": 19},
    "Regal": {"color": "#9a3412", "fill_color": "#f97316", "fill_opacity": 0.55, "line_width": 1.5,
              "label_min_zoom": 20},
    "Schrank": {"color": "#6d28d9", "fill_color": "#8b5cf6", "fill_opacity": 0.55, "line_width": 1.5,
                "label_min_zoom": 20},
}

# What maps 0002 set: a field that still has this value (or none) gets the new look; one changed in the admin stays.
OLD = {
    "Haus+Ebene": {"color": "#111827", "fill_opacity": 0, "line_width": 3},
    "Raum": {"label_min_zoom": 18, "color": "#1d4ed8", "fill_color": "#93c5fd", "fill_opacity": 0.15, "line_width": 2},
    "Teilraum": {"label_min_zoom": 19, "color": "#1d4ed8", "fill_color": "#93c5fd", "fill_opacity": 0.1,
                 "line_width": 1.5},
    "Bereich": {"label_min_zoom": 18, "color": "#b45309", "fill_color": "#fcd34d", "fill_opacity": 0.12,
                "line_width": 2, "style_options": {"dashArray": "8 5"}},
    "Teilbereich": {"label_min_zoom": 19, "color": "#b45309", "fill_color": "#fcd34d", "fill_opacity": 0.08,
                    "line_width": 1.5, "style_options": {"dashArray": "6 4"}},
    "Regal": {"label_min_zoom": 20, "color": "#b35c00", "fill_color": "#fd7e14", "fill_opacity": 0.45},
    "Schrank": {"label_min_zoom": 20, "color": "#59359a", "fill_color": "#a370f7", "fill_opacity": 0.45},
}

# For types without map settings yet (created after maps 0002, e.g. by an import): placing and usual sizes as 0002
# gives them.
KINDS = {"space": ["area"], "storage_unit": ["point", "rectangle"], "container": ["point", "rectangle"]}
PLACING = {
    "Regal": {"default_width_cm": 100, "default_depth_cm": 50},
    "Schrank": {"default_width_cm": 100, "default_depth_cm": 60},
    "Fach/Schub": {"placeable": False},
    "Palette": {"placeable": False, "default_width_cm": 120, "default_depth_cm": 80},
    "Kiste": {"placeable": False, "default_width_cm": 60, "default_depth_cm": 40},
    "Karton": {"placeable": False, "default_width_cm": 60, "default_depth_cm": 40},
    "Mobil": {"placeable": False},
}


def type_looks(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    LocationTypeMap = apps.get_model("maps", "LocationTypeMap")
    parts = set(LocationType.objects.exclude(sublocation_type=None).values_list("sublocation_type_id", flat=True))
    for kind in LocationType.objects.all():
        placing = PLACING.get(kind.name, {})
        shapes = KINDS.get(kind.category or "", ["point"])
        settings, _created = LocationTypeMap.objects.get_or_create(type=kind, defaults={
            "placeable": placing.get("placeable", kind.category in ("space", "storage_unit") and kind.pk not in parts),
            "as_point": "point" in shapes, "as_rectangle": "rectangle" in shapes, "as_area": "area" in shapes,
            "default_width_cm": placing.get("default_width_cm"), "default_depth_cm": placing.get("default_depth_cm")})
        old = OLD.get(kind.name, {})
        for field, value in LOOKS.get(kind.name, {}).items():
            current = getattr(settings, field)
            empty = current is None or current is False or current in ("", {})  # 0 is a value
            if empty or (field in old and current == old[field]):
                setattr(settings, field, value)
        settings.save()


def true_north_rectangles(apps, schema_editor):
    """Rectangles were turned from the north of MAPS_LOCAL_SRID's grid instead of true north (about 1.5° apart in
    Erlangen; the map and the edit mode count from true north): drawn anew from their centre, size and rotation
    (geo.rectangle). Their rotation stays as it was entered."""
    from maps import geo

    LocationShape = apps.get_model("maps", "LocationShape")
    LocationTypeMap = apps.get_model("maps", "LocationTypeMap")
    usual = {settings.type_id: (settings.default_width_cm, settings.default_depth_cm)
             for settings in LocationTypeMap.objects.all()}
    for shape in LocationShape.objects.filter(kind="rectangle", geometry__isnull=False).select_related("location"):
        type_size = usual.get(shape.location.type_id, (None, None))
        width, depth = shape.width_cm or type_size[0], shape.depth_cm or type_size[1]
        if width and depth:  # as LocationShape.size_cm
            shape.geometry = geo.rectangle(geo.anchor(shape.geometry), width / 100, depth / 100, shape.rotation)
            shape.save(update_fields=["geometry"])


class Migration(migrations.Migration):
    dependencies = [("maps", "0003_surveyed_points")]
    operations = [migrations.RunPython(type_looks, migrations.RunPython.noop),
                  migrations.RunPython(true_north_rectangles, migrations.RunPython.noop)]
