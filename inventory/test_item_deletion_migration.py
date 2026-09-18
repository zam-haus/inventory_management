from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ItemDeletionMigrationTests(TransactionTestCase):
    def test_existing_zero_stock_items_are_marked_without_removing_rows(self):
        before = [("inventory", "0015_location_is_deleted")]
        after = [("inventory", "0016_item_is_deleted")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            Item = apps.get_model("inventory", "Item")
            Stock = apps.get_model("inventory", "ItemLocation")
            Location = apps.get_model("inventory", "Location")
            kind = apps.get_model("inventory", "LocationType").objects.create(name="Room", unique=True)
            unit = apps.get_model("inventory", "MeasurementUnit").objects.create(name="Piece", short="pc")
            locations = [Location.objects.create(type=kind, name=f"Room {i}", short_name=f"R{i}", unique_identifier=f"R{i}", locatable_identifier=f"R{i}", descriptive_identifier=f"Room {i}") for i in range(2)]
            cases = [([], True), ([0], True), ([0, 0], True), ([0, 1], False), (["0.001"], False), ([-25], False), ([-1], False), ([-9999], False), ([25, -25], False)]
            expected = {}
            for index, (amounts, deleted) in enumerate(cases):
                item = Item.objects.create(name=f"Case {index}", measurement_unit=unit)
                expected[item.pk] = deleted
                for location, amount in zip(locations, amounts):
                    Stock.objects.create(item=item, location=location, amount=amount)
            count = Stock.objects.count()
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            Item = apps.get_model("inventory", "Item")
            self.assertEqual(dict(Item.objects.values_list("pk", "is_deleted")), expected)
            self.assertEqual(apps.get_model("inventory", "ItemLocation").objects.count(), count)
        finally:
            MigrationExecutor(connection).migrate(after)
