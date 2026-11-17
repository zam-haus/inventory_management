"""A Zebra on a print agent has its labels and ribbon set on the agent's display."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0009_brother_without_half_cut"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printer",
            name="loaded_medium",
            field=models.ForeignKey(
                blank=True,
                help_text="Zebra: the labels in the printer now; set it when changing labels (on a print agent: on its display). Only these are printed, after comparing their height with the label length the printer measured (it cannot tell their width).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="label_printing.labelstock",
                verbose_name="loaded labels",
            ),
        ),
        migrations.AlterField(
            model_name="printer",
            name="loaded_ribbon",
            field=models.ForeignKey(
                blank=True,
                help_text="Zebra: the ribbon in the printer now; set it when changing ribbons (on a print agent: on its display). Its material (wax, wax/resin, resin) is compared with what the loaded labels need, and the print agent's display warns if it does not suit them.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="label_printing.ribbon",
                verbose_name="loaded ribbon",
            ),
        ),
    ]
