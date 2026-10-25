import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Label templates become label designs (label_printing.design) for locations, items, unique items or label IDs,
    with rules for which subjects they are meant; label_printing.0002 describes the ZPL templates anew, 0043 removes
    their ZPL and the templates chosen per location type and location (now rules and the last label printed)."""

    dependencies = [
        ("inventory", "0041_admin_only_locks_purpose"),
        ("label_printing", "0001_initial"),
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
            field=models.CharField(choices=[("location", "location"), ("item", "item"), ("uniqueitem", "unique item"),
                                            ("labelid", "label ID (ZAMid)")],
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
        migrations.CreateModel(
            name="LabelTemplateRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "condition",
                    models.CharField(
                        blank=True,
                        help_text='As in {% if %} with the variables of the labels, e.g. location.type.category == "container"; empty: always.',
                        max_length=500,
                        verbose_name="condition",
                    ),
                ),
                (
                    "priority",
                    models.PositiveSmallIntegerField(
                        default=1,
                        help_text="The highest is preselected; 0: offered only on request, unless none ranks higher.",
                        verbose_name="print priority",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rules",
                        to="inventory.locationlabeltemplate",
                        verbose_name="label template",
                    ),
                ),
            ],
            options={
                "verbose_name": "rule",
                "verbose_name_plural": "rules",
                "ordering": ("-priority", "pk"),
            },
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="background_color",
            field=models.CharField(
                blank=True,
                default="weiß",
                help_text="Only labels or tape of this colour; empty: any.",
                max_length=64,
                verbose_name="background colour",
            ),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="label_stock",
            field=models.ForeignKey(
                blank=True,
                help_text="Only these labels; empty: any of its size, by material and colours.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="label_printing.labelstock",
                verbose_name="label stock",
            ),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="material",
            field=models.CharField(
                blank=True,
                help_text="Only labels of this material, e.g. Polyester; empty: any.",
                max_length=64,
                verbose_name="material",
            ),
        ),
        migrations.AddField(
            model_name="locationlabeltemplate",
            name="print_color",
            field=models.CharField(
                blank=True,
                default="schwarz",
                help_text="Only labels or tape printing in this colour; empty: any.",
                max_length=64,
                verbose_name="print colour",
            ),
        ),
    ]
