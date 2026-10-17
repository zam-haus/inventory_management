"""The location summary becomes its purpose, shown with the location's name. Texts are kept."""
import django.core.validators
from django.db import migrations, models


def rename_history_keys(apps, schema_editor, old="summary", new="purpose"):
    LocationHistory = apps.get_model("inventory", "LocationHistory")
    for entry in LocationHistory.objects.all():
        changed = False
        for snapshot in (entry.before, entry.after):
            if old in snapshot:
                snapshot[new] = snapshot.pop(old)
                changed = True
        if changed:
            entry.save(update_fields=["before", "after"])


def restore_history_keys(apps, schema_editor):
    rename_history_keys(apps, schema_editor, old="purpose", new="summary")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0034_location_type_deletable_in_frontend"),
    ]

    operations = [
        migrations.RenameField(model_name="location", old_name="summary", new_name="purpose"),
        migrations.AlterField(
            model_name="location",
            name="purpose",
            field=models.CharField(
                blank=True, max_length=50, verbose_name="purpose",
                validators=[django.core.validators.RegexValidator(
                    "[\\r\\n]", inverse_match=True, message="The purpose must be a single line.",
                )],
            ),
        ),
        migrations.RunPython(rename_history_keys, restore_history_keys),
    ]
