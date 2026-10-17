"""
ZAM IDs become label IDs: the model, its table, constraints, permission codenames
and triggers get generic names; the name shown to users is settings.LABEL_ID_NAME.
Rows, codes and permission assignments are kept.
"""
import django.db.models.deletion
from django.db import migrations, models

from inventory.label_ids import triggers

COLUMNS = ("item_id", "location_id", "url", "unique_item_id")  # as in 0023_unique_items_squashed_0031

# old codename: (new codename, new name)
PERMISSIONS = {
    "view_zamid": ("view_labelid", "Can view label ID"),
    "change_zamid": ("change_labelid", "Can change label ID"),
    "claim_zamid": ("claim_labelid", "Can claim a label ID for an item, location or unique item"),
    "generate_zamid": ("generate_labelid", "Can generate label IDs"),
    "retire_zamid": ("retire_labelid", "Can retire label IDs"),
    "assign_url_zamid": ("assign_url_labelid", "Can link a label ID to an arbitrary URL"),
}


def drop_old_triggers(apps, schema_editor):
    triggers.uninstall_legacy(schema_editor)  # databases migrated before the triggers were renamed
    triggers.uninstall(schema_editor, triggers.LEGACY_TABLE)


def restore_old_triggers(apps, schema_editor):
    triggers.install(schema_editor, COLUMNS, triggers.LEGACY_TABLE)


def install_triggers(apps, schema_editor):
    triggers.install(schema_editor, COLUMNS)


def uninstall_triggers(apps, schema_editor):
    triggers.uninstall(schema_editor)


def rename_permissions(apps, schema_editor, reverse=False):
    # The content type itself is renamed by Django right after RenameModel.
    Permission = apps.get_model("auth", "Permission")
    for old, (new, name) in PERMISSIONS.items():
        source, target = (new, old) if reverse else (old, new)
        Permission.objects.filter(content_type__app_label="inventory", codename=source).update(
            codename=target, **({} if reverse else {"name": name}))


def restore_permissions(apps, schema_editor):
    rename_permissions(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("inventory", "0023_unique_items_squashed_0031"),
    ]

    operations = [
        migrations.RunPython(drop_old_triggers, restore_old_triggers),
        migrations.RenameModel("ZamId", "LabelId"),
        migrations.RunPython(rename_permissions, restore_permissions),
        migrations.AlterModelOptions(
            name="labelid",
            options={
                "default_permissions": ("view", "change"),
                "ordering": ["-created_at", "code"],
                "permissions": [
                    (
                        "claim_labelid",
                        "Can claim a label ID for an item, location or unique item",
                    ),
                    ("generate_labelid", "Can generate label IDs"),
                    ("retire_labelid", "Can retire label IDs"),
                    ("assign_url_labelid", "Can link a label ID to an arbitrary URL"),
                    ("view_labelid_access_user", "Can see who accessed a label ID"),
                ],
                "verbose_name": "label ID",
                "verbose_name_plural": "label IDs",
            },
        ),
        migrations.RemoveConstraint(
            model_name="labelid",
            name="zamid_one_active_per_item",
        ),
        migrations.RemoveConstraint(
            model_name="labelid",
            name="zamid_one_active_per_location",
        ),
        migrations.RemoveConstraint(
            model_name="labelid",
            name="zamid_status_matches_target",
        ),
        migrations.RemoveConstraint(
            model_name="labelid",
            name="zamid_one_active_per_unique_item",
        ),
        migrations.AlterField(
            model_name="labelid",
            name="item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="label_ids",
                to="inventory.item",
                verbose_name="item",
            ),
        ),
        migrations.AlterField(
            model_name="labelid",
            name="location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="label_ids",
                to="inventory.location",
                verbose_name="location",
            ),
        ),
        migrations.AlterField(
            model_name="labelid",
            name="unique_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="label_ids",
                to="inventory.uniqueitem",
                verbose_name="unique item",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelid",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("status", "reserved"),
                        ("item__isnull", True),
                        ("location__isnull", True),
                        ("unique_item__isnull", True),
                        ("url__isnull", True),
                    ),
                    models.Q(
                        ("status", "assigned"),
                        models.Q(
                            models.Q(
                                ("item__isnull", False),
                                ("location__isnull", True),
                                ("unique_item__isnull", True),
                                ("url__isnull", True),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", False),
                                ("unique_item__isnull", True),
                                ("url__isnull", True),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", True),
                                ("unique_item__isnull", True),
                                ("url__isnull", False),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", True),
                                ("unique_item__isnull", False),
                                ("url__isnull", True),
                            ),
                            _connector="OR",
                        ),
                    ),
                    models.Q(
                        ("status", "retired"),
                        models.Q(
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", True),
                                ("unique_item__isnull", True),
                                ("url__isnull", True),
                            ),
                            models.Q(
                                ("item__isnull", False),
                                ("location__isnull", True),
                                ("unique_item__isnull", True),
                                ("url__isnull", True),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", False),
                                ("unique_item__isnull", True),
                                ("url__isnull", True),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", True),
                                ("unique_item__isnull", True),
                                ("url__isnull", False),
                            ),
                            models.Q(
                                ("item__isnull", True),
                                ("location__isnull", True),
                                ("unique_item__isnull", False),
                                ("url__isnull", True),
                            ),
                            _connector="OR",
                        ),
                    ),
                    _connector="OR",
                ),
                name="label_id_status_matches_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelid",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "assigned")),
                fields=("item",),
                name="label_id_one_active_per_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelid",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "assigned")),
                fields=("location",),
                name="label_id_one_active_per_location",
            ),
        ),
        migrations.AddConstraint(
            model_name="labelid",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "assigned")),
                fields=("unique_item",),
                name="label_id_one_active_per_unique_item",
            ),
        ),
        # SQLite rebuilt the table for the constraints, which dropped any triggers.
        migrations.RunPython(install_triggers, uninstall_triggers),
    ]
