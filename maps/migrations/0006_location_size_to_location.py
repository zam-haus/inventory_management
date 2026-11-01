from django.db import migrations, models


# The size of a location's rectangle is now the location's width and depth (Location.footprint_cm): its own size
# on the map becomes those, where the location has none yet.
def sizes_to_locations(apps, schema_editor):
    Location = apps.get_model("inventory", "Location")
    for shape in apps.get_model("maps", "LocationShape").objects.filter(width_cm__isnull=False,
                                                                       depth_cm__isnull=False):
        Location.objects.filter(pk=shape.location_id, width_cm__isnull=True, depth_cm__isnull=True).update(
            width_cm=shape.width_cm, depth_cm=shape.depth_cm)


def sizes_to_shapes(apps, schema_editor):
    Location = apps.get_model("inventory", "Location")
    for shape in apps.get_model("maps", "LocationShape").objects.filter(kind="rectangle"):
        location = Location.objects.get(pk=shape.location_id)
        if location.width_cm and location.depth_cm:
            shape.width_cm, shape.depth_cm = location.width_cm, location.depth_cm
            shape.save(update_fields=["width_cm", "depth_cm"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0052_location_dimensions"),
        ("maps", "0005_unique_item_shapes"),
    ]

    operations = [
        migrations.RunPython(sizes_to_locations, sizes_to_shapes),
        migrations.RemoveField(model_name="locationshape", name="depth_cm"),
        migrations.RemoveField(model_name="locationshape", name="width_cm"),
    ]
