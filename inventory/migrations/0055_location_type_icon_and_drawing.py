from django.db import migrations, models

# Location types choose their icon and what the page for adding them shows (docs/icons.md,
# docs/location-structure.md). The type Tisch follows in 0056: on PostgreSQL rows and columns of one table do not
# change in one migration.


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0054_location_short_name_characters"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationtype",
            name="icon",
            field=models.CharField(
                blank=True, max_length=64, verbose_name="icon",
                help_text="Shown before the names of its locations and on its add buttons (with a plus). Empty: the "
                          "icon of its category. One of the icons in the inventory; another one is added by copying "
                          "its SVG from icons.getbootstrap.com (docs/icons.md)."),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="numbering_drawing",
            field=models.CharField(
                blank=True, max_length=16, verbose_name="drawing when adding",
                choices=[("shelf", "Shelves side by side, compartments from the bottom up"),
                         ("table", "Tables along a wall from above; from the bottom up: below, drawers, top, above")],
                help_text="Shown when locations of this type are added on the inventory pages: how they are "
                          "numbered."),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="numbering_info",
            field=models.TextField(
                blank=True, verbose_name="text when adding",
                help_text="Shown with it (Markdown), e.g. what to keep in mind when numbering them here."),
        ),
    ]
