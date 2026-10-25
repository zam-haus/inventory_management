from django.db import migrations, models


class Migration(migrations.Migration):
    """The ZPL of label templates, described anew by label_printing.0002, and the templates chosen per location
    type and location: rules of the templates say which are meant for a location, and label_printing.0002 made
    each location's template its last label (LastLabel), preselected when it is printed again."""

    dependencies = [
        ("inventory", "0042_label_designs"),
        ("label_printing", "0002_labels_to_start_with"),
    ]

    operations = [
        # With a default first, so that going back adds the field again to templates without ZPL.
        migrations.AlterField(model_name="locationlabeltemplate", name="zpl_template",
                              field=models.TextField(default="", verbose_name="ZPL template")),
        migrations.RemoveField(model_name="locationlabeltemplate", name="zpl_template"),
        migrations.RemoveField(model_name="location", name="label_template"),
        migrations.RemoveField(model_name="locationtype", name="default_label_template"),
    ]
