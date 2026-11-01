"""
The kind of items tracked as unique items is now called "serialized item" (Einzelartikel), so that it no
longer shares its name with the unique items (Einzelobjekte) themselves: its value becomes "serialized".
Change log entries keep the labels shown when they were recorded; those of the kind are renamed as well.
"""
import django.db.models.deletion
from django.db import migrations, models

LABELS = {"unique items": "serialized item", "Einzelobjekte": "Einzelartikel"}


def relabel(apps, labels):
    ChangeLog = apps.get_model("inventory", "ChangeLog")
    for entry in ChangeLog._base_manager.filter(subject_type="item").exclude(changes=[]).iterator():
        changed = False
        for change in entry.changes:
            if change["field"] == "kind":
                for side in ("before", "after"):
                    if change[side] in labels:
                        change[side], changed = labels[change[side]], True
        if changed:
            entry.save(update_fields=["changes"])


def forwards(apps, schema_editor):
    apps.get_model("inventory", "Item")._base_manager.filter(kind="unique").update(kind="serialized")
    relabel(apps, LABELS)


def backwards(apps, schema_editor):
    apps.get_model("inventory", "Item")._base_manager.filter(kind="serialized").update(kind="unique")
    relabel(apps, {new: old for old, new in LABELS.items()})


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0050_location_path_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="kind",
            field=models.CharField(choices=[("bulk", "bulk item"), ("serialized", "serialized item")],
                                   default="bulk", max_length=16, verbose_name="kind"),
        ),
        migrations.AlterField(
            model_name="uniqueitem",
            name="item",
            field=models.ForeignKey(limit_choices_to={"kind": "serialized"},
                                    on_delete=django.db.models.deletion.PROTECT, related_name="unique_items",
                                    to="inventory.item", verbose_name="item"),
        ),
        migrations.RunPython(forwards, backwards),
    ]
