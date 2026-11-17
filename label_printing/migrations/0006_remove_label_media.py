"""The label media go (0005 moved what they held); the printer's loaded labels and the jobs' labels are label material."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0005_media_to_label_material"),
    ]

    operations = [
        migrations.RemoveField(model_name="printer", name="loaded_medium"),
        migrations.RemoveField(model_name="printjob", name="medium"),
        migrations.DeleteModel(name="LabelMedium"),
        migrations.RenameField(model_name="printer", old_name="loaded_stock", new_name="loaded_medium"),
        migrations.RenameField(model_name="printjob", old_name="stock", new_name="medium"),
        migrations.AlterField(
            model_name="printer",
            name="loaded_medium",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                to="label_printing.labelstock", verbose_name="loaded labels",
                help_text="Zebra: the labels in the printer now; set it when changing labels. Only these are printed, "
                          "after comparing their height with the label length the printer measured (it cannot tell "
                          "their width)."),
        ),
        migrations.AlterField(
            model_name="printjob",
            name="medium",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to="label_printing.labelstock", verbose_name="label material"),
        ),
    ]
