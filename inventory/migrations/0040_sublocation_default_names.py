"""Compartments and drawers with their default name get their shelf's or cabinet's name in front: "Fach c"
becomes "Regal 301 Fach c" (LocationType.sublocation_name). Individually named ones stay as they are.

Migrations have no computed fields, so the descriptive identifiers of the renamed locations and everything
inside them are set here, too. Data only; see 0037 for why it is separate from schema changes.
"""
from django.db import migrations

NAME_LENGTH = 128


def sublocation_name(parent_name, prefix, code):
    # As LocationType.sublocation_name at the time of this migration.
    name = " ".join(part for part in (parent_name, prefix, code) if part)
    return name if len(name) <= NAME_LENGTH else f"{prefix} {code}".strip()


def rename(apps, to_new):
    LocationType = apps.get_model("inventory", "LocationType")
    Location = apps.get_model("inventory", "Location")
    sub_types = LocationType.objects.filter(
        pk__in=LocationType.objects.exclude(sublocation_type=None).values("sublocation_type"))
    for sub in sub_types:
        parts = Location.objects.filter(type=sub, parent_location__isnull=False).select_related("parent_location")
        for part in parts:
            old_name = f"{sub.auto_name_prefix} {part.short_name}".strip()
            new_name = sublocation_name(part.parent_location.name, sub.auto_name_prefix, part.short_name)
            current, target = (old_name, new_name) if to_new else (new_name, old_name)
            if part.name != current or current == target:
                continue
            descriptive = f"{part.parent_location.descriptive_identifier} {target} [{part.short_name}]"
            Location.objects.filter(pk=part.pk).update(name=target, descriptive_identifier=descriptive)
            # Everything inside (e.g. boxes in a compartment) has the compartment's name in its path.
            pending = {part.pk: descriptive}
            while pending:
                children = Location.objects.filter(parent_location_id__in=pending).values_list(
                    "pk", "parent_location_id", "name", "short_name")
                pending = {pk: f"{pending[parent]} {name} [{short}]" for pk, parent, name, short in children}
                for pk, path in pending.items():
                    Location.objects.filter(pk=pk).update(descriptive_identifier=path)


def forward(apps, schema_editor):
    rename(apps, to_new=True)


def backward(apps, schema_editor):
    rename(apps, to_new=False)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0039_storage_units_moveable"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
