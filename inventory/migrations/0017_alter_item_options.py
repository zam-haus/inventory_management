from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("inventory", "0016_item_is_deleted")]

    operations = [
        migrations.AlterModelOptions(
            name="item",
            options={"ordering": ["id"], "verbose_name": "item", "verbose_name_plural": "items"},
        ),
    ]
