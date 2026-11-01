"""
A location's physical description is its description now (the purpose says what it is for). Change log entries
name its field by the new name.
"""
from django.db import migrations, models


def rename_in_change_log(apps, old, new):
    ChangeLog = apps.get_model("inventory", "ChangeLog")
    for entry in ChangeLog._base_manager.filter(subject_type="location").exclude(changes=[]).iterator():
        if any(change["field"] == old for change in entry.changes):
            entry.changes = [{**change, "field": new} if change["field"] == old else change for change in entry.changes]
            entry.save(update_fields=["changes"])


def forwards(apps, schema_editor):
    rename_in_change_log(apps, "physical_description", "description")


def backwards(apps, schema_editor):
    rename_in_change_log(apps, "description", "physical_description")


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0052_location_dimensions"),
    ]

    operations = [
        migrations.RenameField(model_name="location", old_name="physical_description", new_name="description"),
        migrations.AlterField(
            model_name="location",
            name="description",
            field=models.TextField(blank=True, verbose_name="description"),
        ),
        migrations.RunPython(forwards, backwards),
    ]
