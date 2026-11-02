from django.db import migrations

# Tables and workbenches, numbered per room or area like shelves and cabinets (docs/location-structure.md):
# Ti + number (Ti303), drawers and shelves below the top as compartments a–z, with their own icon and drawing.
# Left alone where a type of the name exists already.
TABLE = {
    "name": "Tisch",
    "description": "Tisch oder Werkbank. Code Ti + Nummer aus dem Nummernkreis des Raums oder Bereichs (Ti303); "
                   "Schübe und Fächer a–z.",
    "category": "storage_unit",
    "unique": True,
    "moveable": True,
    "deletable_in_frontend": True,
    "area_numbering": True,
    "auto_name_prefix": "Tisch",
    "auto_short_name_prefix": "Ti",
    "auto_short_name_padding_length": 3,
    "auto_sequence": "0123456789",
    "icon": "furniture-table",
    "numbering_drawing": "table",
}


def add_table(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    # The drawing all area-numbered types showed so far (shelves and cabinets).
    LocationType.objects.filter(area_numbering=True, numbering_drawing="").update(numbering_drawing="shelf")
    if LocationType.objects.filter(name=TABLE["name"]).exists():
        return
    compartment = LocationType.objects.filter(name="Fach/Schub").first()
    LocationType.objects.create(sublocation_type=compartment, **TABLE)


def remove_table(apps, schema_editor):
    apps.get_model("inventory", "LocationType").objects.filter(name=TABLE["name"], location__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0055_location_type_icon_and_drawing"),
    ]

    operations = [
        migrations.RunPython(add_table, remove_table),
    ]
