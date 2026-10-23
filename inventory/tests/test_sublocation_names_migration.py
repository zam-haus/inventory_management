from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SublocationNamesMigrationTests(TransactionTestCase):
    def test_default_names_get_the_shelf_name_and_paths_follow(self):
        before = [("inventory", "0039_storage_units_moveable")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            LocationType = apps.get_model("inventory", "LocationType")
            Location = apps.get_model("inventory", "Location")
            compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach",
                                                      auto_sequence="abcdefghijklmnopqrstuvwxyz")
            shelf_type = LocationType.objects.create(name="Regal", unique=True, auto_name_prefix="Regal",
                                                     auto_short_name_prefix="R", sublocation_type=compartment)
            box_type = LocationType.objects.create(name="Kiste", unique=True)

            def create(type, name, short, parent=None):
                # Historical models compute nothing; the paths are set as the app would.
                return Location.objects.create(
                    type=type, name=name, short_name=short, parent_location=parent,
                    unique_identifier=short if type.unique else f"{parent.unique_identifier}.{short}",
                    locatable_identifier=f"{parent.locatable_identifier}.{short}" if parent else short,
                    descriptive_identifier=f"{parent.descriptive_identifier} {name} [{short}]" if parent
                    else f"{name} [{short}]")

            shelf = create(shelf_type, "Regal 301", "R301")
            default = create(compartment, "Fach a", "a", shelf)
            custom = create(compartment, "Ebene B", "b", shelf)
            box = create(box_type, "Kiste 1", "K0001", default)

            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            Location = executor.loader.project_state(latest).apps.get_model("inventory", "Location")
            self.assertEqual(Location.objects.get(pk=default.pk).name, "Regal 301 Fach a")
            self.assertEqual(Location.objects.get(pk=default.pk).descriptive_identifier,
                             "Regal 301 [R301] Regal 301 Fach a [a]")
            self.assertEqual(Location.objects.get(pk=box.pk).descriptive_identifier,
                             "Regal 301 [R301] Regal 301 Fach a [a] Kiste 1 [K0001]")
            self.assertEqual(Location.objects.get(pk=custom.pk).name, "Ebene B")

            executor = MigrationExecutor(connection)
            executor.migrate(before)
            Location = executor.loader.project_state(before).apps.get_model("inventory", "Location")
            self.assertEqual(Location.objects.get(pk=default.pk).name, "Fach a")
            self.assertEqual(Location.objects.get(pk=box.pk).descriptive_identifier,
                             "Regal 301 [R301] Fach a [a] Kiste 1 [K0001]")
        finally:
            MigrationExecutor(connection).migrate(latest)
