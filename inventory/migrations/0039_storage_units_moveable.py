"""Shelves and cabinets (types with number ranges per area) can be moved, e.g. onto a pallet; they keep their number."""
from django.db import migrations


def forward(apps, schema_editor):
    apps.get_model("inventory", "LocationType").objects.filter(area_numbering=True).update(moveable=True)


def backward(apps, schema_editor):
    apps.get_model("inventory", "LocationType").objects.filter(area_numbering=True).update(moveable=False)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0038_location_former_codes"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
