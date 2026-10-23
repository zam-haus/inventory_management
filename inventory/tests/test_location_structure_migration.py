from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LocationStructureMigrationTests(TransactionTestCase):
    def test_existing_types_get_category_and_sequence_on_a_populated_database(self):
        # On PostgreSQL, changing a type row twice in the transaction that also creates indexes on its
        # table failed with "pending trigger events" once the type had a label template (production).
        before = [("inventory", "0035_location_purpose")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            template = apps.get_model("inventory", "LocationLabelTemplate").objects.create(
                name="Box", zpl_template="", label_width=50, label_height=25)
            LocationType = apps.get_model("inventory", "LocationType")
            box = LocationType.objects.create(name="Kiste", moveable=True, unique=True, auto_short_name_prefix="K",
                                              auto_sequence="0123456789abcdef", default_label_template=template)
            shelf = LocationType.objects.create(name="Regal", unique=True, auto_short_name_prefix="R",
                                                auto_sequence="0123456789", default_label_template=template)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            types = apps.get_model("inventory", "LocationType").objects
            self.assertEqual(types.get(pk=box.pk).category, "container")
            self.assertEqual(types.get(pk=box.pk).auto_sequence, "0123456789")
            self.assertEqual(types.get(pk=shelf.pk).category, "")
        finally:
            MigrationExecutor(connection).migrate(latest)
