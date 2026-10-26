from django.db import migrations

RRZE = "https://osm.rrze.fau.de"
# Background maps from the tile server of the FAU Erlangen-Nürnberg (https://osm.rrze.fau.de), changed in the admin.
LAYERS = [
    {"name": "Luftbild Erlangen 2018", "url": RRZE + "/luftbilderl2018/{z}/{x}/{y}.jpg", "max_zoom": 20,
     "attribution": "© Stadt Erlangen | © Hansa Luftbild AG (CC BY 4.0)", "is_default": True},
    {"name": "Luftbild Bayern (DOP20)", "url": RRZE + "/bayerndop20/{z}/{x}/{y}.jpg", "max_zoom": 19,
     "attribution": "Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC BY 4.0)"},
    {"name": "RRZE Tileserver (osm.de-Stil)", "url": RRZE + "/osmde/{z}/{x}/{y}.png", "max_zoom": 19,
     "attribution": "© OpenStreetMap-Mitwirkende (ODbL)"},
]


# The shapes of locations on the map, by category (as permissions.DEFAULT_KINDS).
KINDS = {"space": ["area"], "storage_unit": ["point", "rectangle"], "container": ["point", "rectangle"]}

# Map settings of the location types in use at ZAM, by name; other types follow their category (permissions.py
# default_placed). Only empty fields are filled, so settings made in the admin stay.
TYPES = {
    "Haus+Ebene": {"color": "#111827", "fill_opacity": 0, "line_width": 3},
    # Rooms (walls and a door): solid; areas (no walls of their own, docs/standortregeln.md): dashed, as their
    # boundaries are loosely defined.
    "Raum": {"label_min_zoom": 18, "color": "#1d4ed8", "fill_color": "#93c5fd", "fill_opacity": 0.15,
             "line_width": 2},
    "Teilraum": {"label_min_zoom": 19, "color": "#1d4ed8", "fill_color": "#93c5fd", "fill_opacity": 0.1,
                 "line_width": 1.5},
    "Bereich": {"label_min_zoom": 18, "color": "#b45309", "fill_color": "#fcd34d", "fill_opacity": 0.12,
                "line_width": 2, "style_options": {"dashArray": "8 5"}},
    "Teilbereich": {"label_min_zoom": 19, "color": "#b45309", "fill_color": "#fcd34d", "fill_opacity": 0.08,
                    "line_width": 1.5, "style_options": {"dashArray": "6 4"}},
    "Regal": {"label_min_zoom": 20, "default_width_cm": 100, "default_depth_cm": 50, "color": "#b35c00",
              "fill_color": "#fd7e14", "fill_opacity": 0.45},
    "Schrank": {"label_min_zoom": 20, "default_width_cm": 100, "default_depth_cm": 60, "color": "#59359a",
                "fill_color": "#a370f7", "fill_opacity": 0.45},
    "Fach/Schub": {"placeable": False},
    "Palette": {"placeable": False, "default_width_cm": 120, "default_depth_cm": 80},
    "Kiste": {"placeable": False, "default_width_cm": 60, "default_depth_cm": 40},
    "Karton": {"placeable": False, "default_width_cm": 60, "default_depth_cm": 40},
    "Mobil": {"placeable": False},
}


def initial_data(apps, schema_editor):
    """Map settings of the location types: levels, rooms, areas and storage units are placeable, containers and the
    parts of storage units (compartments) not; looks and usual sizes of the types in use (TYPES). Background
    layers."""
    LocationType = apps.get_model("inventory", "LocationType")
    LocationTypeMap = apps.get_model("maps", "LocationTypeMap")
    parts = set(LocationType.objects.exclude(sublocation_type=None).values_list("sublocation_type_id", flat=True))
    for kind in LocationType.objects.all():
        defaults = TYPES.get(kind.name, {})
        shapes = KINDS.get(kind.category or "", ["point"])
        settings, created = LocationTypeMap.objects.get_or_create(type=kind, defaults={
            "placeable": defaults.get("placeable", kind.category in ("space", "storage_unit") and kind.pk not in parts),
            "as_point": "point" in shapes, "as_rectangle": "rectangle" in shapes, "as_area": "area" in shapes})
        for field, value in defaults.items():
            if field != "placeable" and getattr(settings, field) in (None, "", {}):
                setattr(settings, field, value)
        settings.save()
    BackgroundLayer = apps.get_model("maps", "BackgroundLayer")
    for position, layer in enumerate(LAYERS):
        BackgroundLayer.objects.get_or_create(name=layer["name"], defaults={**layer, "position": position})


class Migration(migrations.Migration):
    dependencies = [("maps", "0001_initial")]
    operations = [migrations.RunPython(initial_data, migrations.RunPython.noop)]
