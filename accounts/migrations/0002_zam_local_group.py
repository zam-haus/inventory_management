from django.db import migrations


def create_local_group(apps, schema_editor):
    alias = schema_editor.connection.alias
    group, _ = apps.get_model("auth", "Group").objects.using(alias).get_or_create(name="ZAM-local")
    content_types = apps.get_model("contenttypes", "ContentType").objects.using(alias)
    permissions = apps.get_model("auth", "Permission").objects.using(alias)
    # Permissions are normally created after migrations. Create these explicitly
    # so this works on both fresh installations and existing databases.
    for model in apps.get_app_config("inventory").get_models():
        opts = model._meta
        content_type, _ = content_types.get_or_create(app_label="inventory", model=opts.model_name)
        for action in ("add", "change"):
            permission, _ = permissions.get_or_create(
                content_type=content_type, codename=f"{action}_{opts.model_name}",
                defaults={"name": f"Can {action} {opts.verbose_name}"},
            )
            group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("inventory", "0017_alter_item_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_local_group, migrations.RunPython.noop)]
