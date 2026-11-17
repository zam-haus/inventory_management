from django.db import migrations

# Shelf levels and drawers become types of their own (docs/location-structure.md): "Fach/Schub" is "Fach" (a
# compartment or level of a shelf or cabinet; labels with arrows to colour in), the new "Schub" is a drawer (of a
# table or cabinet; short, so its names stay short). Compartments of tables become drawers, and their names made
# from the type ("Tisch 23 Fach a") follow ("Tisch 23 Schub a"); names given by hand stay.
COMPARTMENT = {"name": "Fach", "description": "Fach oder Boden eines Regals oder Schranks. Kleinbuchstabe a–z, "
                                              "eindeutig im Regal oder Schrank (R303.a)."}
DRAWER = {"name": "Schub", "auto_name_prefix": "Schub",
          "description": "Schublade eines Tischs oder Schranks. Kleinbuchstabe a–z, eindeutig im Tisch oder Schrank "
                         "(Ti303.a)."}
JOINED = {"name": "Fach/Schub", "description": "Fach eines Regals oder Schublade eines Schranks. Kleinbuchstabe a–z, "
                                               "eindeutig im Regal oder Schrank (R303.a)."}
NAME_LENGTH = 128


def sublocation_name(parent_name, prefix, code):
    # As LocationType.sublocation_name at the time of this migration (and 0040).
    name = " ".join(part for part in (parent_name, prefix, code) if part)
    return name if len(name) <= NAME_LENGTH else f"{prefix} {code}".strip()


def move(Location, locations, to_type, old_prefix, new_prefix):
    """The locations become of `to_type`; names made from the old prefix (also the short form "Fach a") follow the
    new one. Migrations have no computed fields: the paths of the renamed ones and everything inside are set here."""
    for location in locations.select_related("parent_location"):
        parent, code = location.parent_location, location.short_name
        parent_name = parent.name if parent else ""
        name = {sublocation_name(parent_name, old_prefix, code): sublocation_name(parent_name, new_prefix, code),
                f"{old_prefix} {code}".strip(): f"{new_prefix} {code}".strip()}.get(location.name, location.name)
        if name == location.name:
            Location.objects.filter(pk=location.pk).update(type=to_type)
            continue
        path = f"{parent.descriptive_identifier + ' ' if parent else ''}{name} [{code}]"
        Location.objects.filter(pk=location.pk).update(type=to_type, name=name, descriptive_identifier=path)
        pending = {location.pk: path}
        while pending:  # e.g. boxes in a drawer have its name in their paths
            children = Location.objects.filter(parent_location_id__in=pending).values_list(
                "pk", "parent_location_id", "name", "short_name")
            pending = {pk: f"{pending[parent_pk]} {child} [{short}]" for pk, parent_pk, child, short in children}
            for pk, child_path in pending.items():
                Location.objects.filter(pk=pk).update(descriptive_identifier=child_path)


def split(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    Location = apps.get_model("inventory", "Location")
    compartment = LocationType.objects.filter(name=JOINED["name"]).first()
    if compartment is None:
        return
    drawer = LocationType.objects.filter(name=DRAWER["name"]).first()
    if drawer is None:  # a copy of the compartment: the same rules, numbering and category
        drawer = LocationType.objects.get(pk=compartment.pk)
        drawer.pk = None
        for field, value in DRAWER.items():
            setattr(drawer, field, value)
        drawer.save()
    LocationType.objects.filter(pk=compartment.pk).update(**COMPARTMENT)
    LocationType.objects.filter(name="Tisch", sublocation_type=compartment).update(sublocation_type=drawer)
    move(Location, Location.objects.filter(type=compartment, parent_location__type__name="Tisch"), drawer,
         compartment.auto_name_prefix, drawer.auto_name_prefix)


def join(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    Location = apps.get_model("inventory", "Location")
    compartment = LocationType.objects.filter(name=COMPARTMENT["name"]).first()
    if compartment is None:
        return
    drawer = LocationType.objects.filter(name=DRAWER["name"]).first()
    if drawer is not None:
        move(Location, Location.objects.filter(type=drawer), compartment, drawer.auto_name_prefix,
             compartment.auto_name_prefix)
        LocationType.objects.filter(sublocation_type=drawer).update(sublocation_type=compartment)
        drawer.delete()
    LocationType.objects.filter(pk=compartment.pk).update(**JOINED)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0056_table_location_type"),
    ]

    operations = [
        migrations.RunPython(split, join),
    ]
