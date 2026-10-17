from django.db import migrations

from inventory.label_ids import triggers

# Target columns at this point in history. A migration adding a target
# (e.g. asset_id) calls triggers.install() again with the extended list.
COLUMNS = ("item_id", "location_id", "url")


def install_triggers(apps, schema_editor):
    triggers.install(schema_editor, COLUMNS, triggers.LEGACY_TABLE)


def uninstall_triggers(apps, schema_editor):
    triggers.uninstall(schema_editor, triggers.LEGACY_TABLE)


def grant_claim(apps, schema_editor):
    """ZAM-local members may claim labels; nothing else about ZAM IDs."""
    alias = schema_editor.connection.alias
    group, _ = apps.get_model("auth", "Group").objects.using(alias).get_or_create(name="ZAM-local")
    content_type, _ = apps.get_model("contenttypes", "ContentType").objects.using(alias).get_or_create(
        app_label="inventory", model="zamid")
    # Permissions are normally created after migrations; create this one explicitly.
    permission, _ = apps.get_model("auth", "Permission").objects.using(alias).get_or_create(
        content_type=content_type, codename="claim_zamid",
        defaults={"name": "Can claim a ZAM ID for an item or location"},
    )
    group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0021_zamid"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [
        migrations.RunPython(install_triggers, uninstall_triggers),
        migrations.RunPython(grant_claim, migrations.RunPython.noop),
    ]
