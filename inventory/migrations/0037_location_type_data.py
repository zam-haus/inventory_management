"""Existing location types: moveable ones are containers from now on. Sequences are digits or letters
only: types with a mixed sequence (hexadecimal boxes, alphanumeric pallets) count in digits; existing
codes stay as they are and creating new locations skips codes that are taken.

Separate from 0036: on PostgreSQL, rows changed in the transaction that then creates indexes on
their table make the index creation fail ("pending trigger events").
"""
from django.db import migrations

NUMERIC = "0123456789"
KEPT_SEQUENCES = {NUMERIC, "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def forward(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    LocationType.objects.filter(moveable=True).update(category="container")
    LocationType.objects.exclude(auto_sequence__isnull=True).exclude(auto_sequence="").exclude(
        auto_sequence__in=KEPT_SEQUENCES).update(auto_sequence=NUMERIC)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0036_location_structure"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
