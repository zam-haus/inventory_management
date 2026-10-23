from django.conf import settings
from django.db import migrations


def grant_print_label_to_local_group(apps, schema_editor):
    # Members recognized on the local network may print labels from the inventory pages.
    alias = schema_editor.connection.alias
    group, _ = apps.get_model("auth", "Group").objects.using(alias).get_or_create(
        name=getattr(settings, "LOCAL_GROUP_NAME", "ZAM-local"))
    content_type, _ = apps.get_model("contenttypes", "ContentType").objects.using(alias).get_or_create(
        app_label="label_printing", model="printjob",
    )
    permission, _ = apps.get_model("auth", "Permission").objects.using(alias).get_or_create(
        content_type=content_type, codename="print_label", defaults={"name": "Can print labels"},
    )
    group.permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("label_printing", "0001_initial"),
        ("accounts", "0002_zam_local_group"),
    ]

    operations = [
        migrations.RunPython(grant_print_label_to_local_group, migrations.RunPython.noop),
    ]
