from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


# Where the maps show up in the inventory's pages (inventory/slots.py).
SLOTS = [
    ("navbar.items", "maps/slots/navbar_item.html"),
    ("navbar.menu", "maps/slots/navbar_menu.html"),
    ("location_detail.actions", "maps/slots/location_actions.html"),
    ("location_detail.dialogs", "maps/slots/location_dialogs.html"),
    ("location_detail.scripts", "maps/slots/scripts.html"),
    ("location_move.extra", "maps/slots/location_move.html"),
    ("unique_item_detail.actions", "maps/slots/unique_item_actions.html"),
    ("unique_item_detail.dialogs", "maps/slots/unique_item_dialogs.html"),
    ("unique_item_detail.scripts", "maps/slots/scripts.html"),
    ("unique_item_move.extra", "maps/slots/unique_item_move.html"),
    ("result_entries.start", "maps/slots/result_entries.html"),
    ("result_entry.place", "maps/slots/result_entry.html"),
    ("location_info.links", "maps/slots/location_info.html"),
    ("location_info.body", "maps/slots/location_info_body.html"),
    ("base.scripts", "maps/slots/base_scripts.html"),
    ("structure_overview.level", "maps/slots/structure_level.html"),
]


class MapsConfig(AppConfig):
    """Floor plans and positions of locations and unique items (docs/maps.md); optional, see MAPS_ENABLED."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "maps"
    verbose_name = _("Maps")

    def ready(self):
        from inventory import admin_links, slots
        from inventory.change_log import APP_FIELDS
        from inventory.public_export import EXCLUDED_MODELS

        from . import positions, signals
        signals.connect()
        for slot, template in SLOTS:
            slots.register(slot, template)
        # The navbar's Admin link on the map pages: the maps in the admin; the plans, the plan being aligned.
        admin_links.register_page("map", "maps")
        admin_links.register_page("level", "maps")
        admin_links.register_page("plans", "maps.floorplan")
        admin_links.register_object_name("plan")
        # Not in the public data export yet: a development database without maps could not import it.
        EXCLUDED_MODELS.update({
            "maps.floorplan": "building plans; their sources can name people in their metadata",
            "maps.locationshape": "maps are optional; not exported yet",
            "maps.locationtypemap": "maps are optional; not exported yet",
            "maps.backgroundlayer": "maps are optional; each installation chooses its tile servers",
            "maps.uniqueitemposition": "maps are optional; not exported yet",
            "maps.surveyedpoint": "maps are optional; ZAM's points come with migration maps 0003",
            # The spatial database's own tables, which GeoDjango maps (unmanaged) once its backend is loaded.
            "gis.postgisgeometrycolumns": "PostGIS metadata, not inventory data",
            "gis.postgisspatialrefsys": "PostGIS metadata, not inventory data",
            "gis.spatialitegeometrycolumns": "SpatiaLite metadata, not inventory data",
            "gis.spatialitespatialrefsys": "SpatiaLite metadata, not inventory data",
        })
        APP_FIELDS[("location", positions.FIELD)] = _("Position on the map")
        APP_FIELDS[("uniqueitem", positions.FIELD)] = _("Position on the map")
