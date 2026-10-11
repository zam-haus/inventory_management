from django.db import migrations

from zamid import triggers

# Target columns at this point in history. A migration adding a target
# (e.g. asset_id) calls triggers.install() again with the extended list.
COLUMNS = ("item_id", "location_id", "url")


def install(apps, schema_editor):
    triggers.install(schema_editor, COLUMNS)


def uninstall(apps, schema_editor):
    triggers.uninstall(schema_editor)


class Migration(migrations.Migration):
    dependencies = [("zamid", "0001_initial")]
    operations = [migrations.RunPython(install, uninstall)]
