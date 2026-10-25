import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Label templates become label designs (label_printing.design) for locations, bulk items or unique items;
    label_printing.0002 describes the ZPL templates anew, 0043 removes their ZPL."""

    dependencies = [
        ("inventory", "0041_admin_only_locks_purpose"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="locationlabeltemplate",
            options={"ordering": ("name", models.F("label_width").asc(nulls_first=True), "label_height"),
                     "verbose_name": "label template", "verbose_name_plural": "label templates"},
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="subject_type",
            field=models.CharField(choices=[("location", "location"), ("item", "bulk item"),
                                            ("labelid", "unique item (ZAMid)")],
                                   default="location", max_length=16, verbose_name="labels for"),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="description",
            field=models.TextField(default="", verbose_name="label description"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="quality",
            field=models.CharField(
                choices=[("draft", "draft (fast)"), ("standard", "standard"), ("high", "high quality (slower)")],
                default="standard", max_length=16, verbose_name="print quality",
                help_text="Its labels are printed in this quality. Brother: draft printing, or twice the resolution "
                          "along the tape; Zebra: print speed."),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="is_active",
            field=models.BooleanField(default=True, help_text="Only active templates are offered and printed.",
                                      verbose_name="active"),
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
