import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Label templates become label designs (label_printing.design) for locations, items or label IDs; the
    ZPL is converted by label_printing.0008 and removed by 0044."""

    dependencies = [
        ("inventory", "0042_location_label_url"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="locationlabeltemplate",
            options={"ordering": ("name",), "verbose_name": "label template", "verbose_name_plural": "label templates"},
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="subject_type",
            field=models.CharField(choices=[("location", "location"), ("item", "item"), ("labelid", "label ID")],
                                   default="location", max_length=16, verbose_name="labels for"),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="description",
            field=models.TextField(default="", verbose_name="label description"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="locationlabeltemplate",
            name="label_width",
            field=models.FloatField(editable=False, help_text="Empty: as long as the content (Brother tape).",
                                    null=True, verbose_name="width (mm)"),
        ),
        migrations.AlterField(
            model_name="locationlabeltemplate",
            name="label_height",
            field=models.FloatField(editable=False, null=True, verbose_name="height (mm)"),
        ),
        migrations.AlterField(
            model_name="location",
            name="label_template",
            field=models.ForeignKey(blank=True, limit_choices_to={"subject_type": "location"}, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    to="inventory.locationlabeltemplate", verbose_name="label template"),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="default_label_template",
            field=models.ForeignKey(blank=True, limit_choices_to={"subject_type": "location"}, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    to="inventory.locationlabeltemplate", verbose_name="default label template"),
        ),
    ]
