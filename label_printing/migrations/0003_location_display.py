"""
The location display rule on labels too (docs/locations.md): what a location is called first, its purpose, else its
name (location.title), its code after it as inverted monospace. Templates as label_printing 0002 brought them are
updated (catalog/location_display_0003.json: before and after); templates changed since are left as they are.
"""
import json
from pathlib import Path

from django.db import migrations

CHANGES = Path(__file__).resolve().parent.parent / "catalog" / "location_display_0003.json"


def changes():
    """[{name, subject_type, label_width, label_height, before, after}]"""
    with open(CHANGES, encoding="utf-8") as file:
        return json.load(file)


def replace(apps, old, new):
    Template = apps.get_model("inventory", "LocationLabelTemplate")
    for change in changes():
        Template.objects.filter(name=change["name"], subject_type=change["subject_type"],
                                label_width=change["label_width"], label_height=change["label_height"],
                                description=change[old]).update(description=change[new])


def forwards(apps, schema_editor):
    replace(apps, "before", "after")


def backwards(apps, schema_editor):
    replace(apps, "after", "before")


class Migration(migrations.Migration):
    dependencies = [("label_printing", "0002_labels_to_start_with")]

    operations = [migrations.RunPython(forwards, backwards)]
