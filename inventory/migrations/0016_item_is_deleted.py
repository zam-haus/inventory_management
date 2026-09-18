from django.db import migrations, models


def mark_unstocked_items_deleted(apps, schema_editor):
    Item = apps.get_model("inventory", "Item")
    ItemLocation = apps.get_model("inventory", "ItemLocation")
    alias = schema_editor.connection.alias
    # Negative quantities denote estimates/few/many, not a lack of stock.
    nonzero_stock = ItemLocation.objects.using(alias).filter(
        item_id=models.OuterRef("pk"),
    ).exclude(amount=0)
    Item.objects.using(alias).annotate(
        has_stock=models.Exists(nonzero_stock),
    ).filter(has_stock=False).update(is_deleted=True)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0015_location_is_deleted")]

    operations = [
        migrations.AddField(
            model_name="item",
            name="is_deleted",
            field=models.BooleanField(default=False, db_index=True, verbose_name="deleted"),
        ),
        migrations.RunPython(mark_unstocked_items_deleted, migrations.RunPython.noop),
    ]
