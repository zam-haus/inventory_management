from django.db import migrations


def grant_claim(apps, schema_editor):
    alias = schema_editor.connection.alias
    group, _ = apps.get_model("auth", "Group").objects.using(alias).get_or_create(name="ZAM-local")
    content_type, _ = apps.get_model("contenttypes", "ContentType").objects.using(alias).get_or_create(
        app_label="zamid", model="zamid")
    # Permissions are normally created after migrations; create this one explicitly.
    permission, _ = apps.get_model("auth", "Permission").objects.using(alias).get_or_create(
        content_type=content_type, codename="claim_zamid",
        defaults={"name": "Can claim a ZAM ID for an item or location"},
    )
    group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("zamid", "0002_immutability_triggers"),
        ("accounts", "0002_zam_local_group"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(grant_claim, migrations.RunPython.noop)]
