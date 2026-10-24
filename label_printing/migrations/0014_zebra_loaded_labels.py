import django.db.models.deletion
from django.db import migrations, models


def default_as_loaded(apps, schema_editor):
    """Zebras start with their default medium (else their first) as the loaded labels; admins change it."""
    for printer in apps.get_model("label_printing", "Printer").objects.filter(language="zpl"):
        printer.loaded_medium = printer.media.order_by("-is_default", "name").first()
        printer.save(update_fields=["loaded_medium"])


class Migration(migrations.Migration):
    """Zebra printers: which labels are loaded is set in the admin (the printer only measures their length)."""

    dependencies = [
        ("label_printing", "0013_template_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="printer",
            name="loaded_medium",
            field=models.ForeignKey(
                blank=True,
                help_text="Zebra: the labels in the printer now; set it when changing labels. Only these are printed, after comparing their height with the label length the printer measured (it cannot tell their width).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="label_printing.labelmedium",
                verbose_name="loaded labels",
            ),
        ),
        migrations.RunPython(default_as_loaded, migrations.RunPython.noop),
    ]
