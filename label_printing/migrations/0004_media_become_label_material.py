"""
Label media per printer (LabelMedium) give way to label material on hand (LabelStock.in_stock): a printer prints on
the material it takes (Printer.takes). What the media held moves on: their offsets to their printer, darkness and
quality to their material, the loaded medium and the jobs' media to their material (0005; in loaded_stock and stock
until 0006 replaces the old fields). New: ribbons, roll core and winding, what the printers take, holding and pausing.
"""
import django.db.models.deletion
from django.db import migrations, models

QUALITY = models.CharField(
    choices=[("draft", "draft (fast)"), ("standard", "standard"), ("high", "high quality (slower)")],
    default="standard", max_length=16, verbose_name="print quality",
    help_text="Unless the label template sets it. Brother: draft printing or high resolution; Zebra: print speed.")
WINDING = [("outside", "outside"), ("inside", "inside")]


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0003_location_display"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="labelstock",
            options={"ordering": ("language", "tape_mm", "width_mm", "height_mm", "code", "name"),
                     "verbose_name": "label material", "verbose_name_plural": "label material"},
        ),
        migrations.AlterField(
            model_name="labelstock",
            name="height_mm",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="height (mm)",
                help_text="Zebra: the label height. Brother: a fixed label length; empty for as long as the content."),
        ),
        migrations.AddField(
            model_name="labelstock",
            name="core_mm",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True,
                                      verbose_name="roll core (mm)",
                                      help_text="Zebra: inner diameter of the core, e.g. 25.4 (1 inch)."),
        ),
        migrations.AddField(
            model_name="labelstock",
            name="in_stock",
            field=models.BooleanField(default=False, verbose_name="on hand",
                                      help_text="Only material on hand is offered for printing and waited for."),
        ),
        migrations.AddField(model_name="labelstock", name="quality", field=QUALITY),
        migrations.AddField(
            model_name="labelstock",
            name="winding",
            field=models.CharField(blank=True, choices=WINDING, max_length=8, verbose_name="labels wound",
                                   help_text="Zebra: printed side outside or inside on the roll."),
        ),
        migrations.AddField(
            model_name="labelstock",
            name="zpl_darkness",
            field=models.SmallIntegerField(blank=True, null=True, verbose_name="darkness",
                                           help_text="Zebra: -30 to 30 (^MD); empty for the printer's setting."),
        ),
        migrations.AlterField(
            model_name="printer",
            name="model",
            field=models.CharField(
                blank=True, max_length=32, verbose_name="model",
                help_text="Brother: E550W, P700, P750W, P710BT, P900, P900W, P950NW or P910BT. Zebra: for information "
                          "only."),
        ),
        migrations.AddField(
            model_name="printer",
            name="core_mm",
            field=models.DecimalField(
                blank=True, decimal_places=1, max_digits=4, null=True, verbose_name="roll core (mm)",
                help_text="Zebra: the core of the label rolls it holds, e.g. 25.4 (1 inch). Filled in from the model."),
        ),
        migrations.AddField(
            model_name="printer",
            name="held_at",
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name="held since"),
        ),
        migrations.AddField(
            model_name="printer",
            name="max_width_mm",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="widest labels (mm)",
                help_text="Zebra: the widest labels; Brother: the widest tape. Filled in from the model."),
        ),
        migrations.AddField(
            model_name="printer",
            name="offset_x",
            field=models.SmallIntegerField(default=0, help_text="Zebra: label home (^LH).",
                                           verbose_name="offset x (dots)"),
        ),
        migrations.AddField(
            model_name="printer",
            name="offset_y",
            field=models.SmallIntegerField(
                default=0, verbose_name="offset y (dots)",
                help_text="Zebra: label home (^LH). Brother: moves the print across the tape, positive = down, if the "
                          "top or bottom is cut off (print the calibration label to measure)."),
        ),
        migrations.AddField(
            model_name="printer",
            name="resume_requested",
            field=models.BooleanField(default=False, editable=False, verbose_name="asked to go on"),
        ),
        migrations.AddField(
            model_name="printer",
            name="thermal_transfer",
            field=models.BooleanField(
                default=True, verbose_name="prints thermal transfer",
                help_text="Zebra: has a ribbon; off for direct thermal models (e.g. GK420d). Filled in from the "
                          "model."),
        ),
        migrations.AddField(
            model_name="printer",
            name="winding",
            field=models.CharField(
                blank=True, choices=WINDING, max_length=8, verbose_name="labels wound",
                help_text="Zebra: the labels on the roll it takes, outside or inside; empty: either. Filled in from "
                          "the model."),
        ),
        migrations.CreateModel(
            name="Ribbon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("material", models.CharField(
                    choices=[("wax", "wax ribbon"), ("wax_resin", "wax/resin ribbon"), ("resin", "resin ribbon")],
                    max_length=16, verbose_name="material")),
                ("width_mm", models.PositiveSmallIntegerField(verbose_name="width (mm)")),
                ("color", models.CharField(
                    default="schwarz", max_length=64, verbose_name="colour",
                    help_text="What a Zebra prints in with this ribbon (label templates and previews).")),
            ],
            options={
                "verbose_name": "ribbon",
                "verbose_name_plural": "ribbons",
                "ordering": ("width_mm", "color", "material"),
                "constraints": [models.UniqueConstraint(fields=("material", "width_mm", "color"),
                                                        name="ribbon_unique")],
            },
        ),
        migrations.AddField(
            model_name="printer",
            name="loaded_ribbon",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                to="label_printing.ribbon", verbose_name="loaded ribbon",
                help_text="Zebra: the ribbon in the printer now; set it when changing ribbons. Its material (wax, "
                          "wax/resin, resin) is compared with what the loaded labels need, and the print agent's "
                          "display warns if it does not suit them."),
        ),
        migrations.AddField(
            model_name="printjob",
            name="command",
            field=models.CharField(blank=True, choices=[("pause", "pause"), ("resume", "go on"), ("abort", "abort")],
                                   max_length=8, verbose_name="command for the print agent"),
        ),
        migrations.AddField(
            model_name="printjob",
            name="paused_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="paused since"),
        ),
        # Until 0006: the material of the loaded medium and of the jobs' media (0005)
        migrations.AddField(
            model_name="printer",
            name="loaded_stock",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                                    to="label_printing.labelstock"),
        ),
        migrations.AddField(
            model_name="printjob",
            name="stock",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                                    to="label_printing.labelstock"),
        ),
    ]
