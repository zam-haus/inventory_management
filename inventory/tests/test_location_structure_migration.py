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

    def test_compartments_of_tables_become_drawers_with_the_paths_inside(self):
        before, after = [("inventory", "0056_table_location_type")], [("inventory", "0057_split_compartments_and_drawers")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            LocationType, Location = apps.get_model("inventory", "LocationType"), apps.get_model("inventory", "Location")
            compartment, _created = LocationType.objects.get_or_create(
                name="Fach/Schub", defaults={"auto_name_prefix": "Fach", "auto_sequence": "abcdefghijklmnopqrstuvwxyz"})
            table, _created = LocationType.objects.get_or_create(name="Tisch", defaults={"auto_name_prefix": "Tisch"})
            box = LocationType.objects.create(name="Box")

            def place(kind, name, short, parent=None):
                path = f"{parent.descriptive_identifier} {name} [{short}]" if parent else f"{name} [{short}]"
                return Location.objects.create(type=kind, name=name, short_name=short, unique_identifier=short,
                                               locatable_identifier=short, descriptive_identifier=path,
                                               parent_location=parent)

            desk = place(table, "Tisch 23", "Ti23")
            made = place(compartment, "Tisch 23 Fach a", "a", desk)
            inner = place(box, "Kiste 1", "K1", made)
            short = place(compartment, "Fach b", "b", desk)  # the short form of a name too long
            named = place(compartment, "Lötzeug", "c", desk)
            ids = (made.pk, inner.pk, short.pk, named.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            locations = apps.get_model("inventory", "Location").objects
            self.assertEqual([(location.type.name, location.name, location.descriptive_identifier)
                              for location in (locations.get(pk=pk) for pk in ids)],
                             [("Schub", "Tisch 23 Schub a", "Tisch 23 [Ti23] Tisch 23 Schub a [a]"),
                              ("Box", "Kiste 1", "Tisch 23 [Ti23] Tisch 23 Schub a [a] Kiste 1 [K1]"),
                              ("Schub", "Schub b", "Tisch 23 [Ti23] Schub b [b]"),
                              ("Schub", "Lötzeug", "Tisch 23 [Ti23] Lötzeug [c]")])
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            locations = apps.get_model("inventory", "Location").objects
            self.assertEqual([locations.get(pk=pk).descriptive_identifier for pk in ids[:3]],
                             ["Tisch 23 [Ti23] Tisch 23 Fach a [a]", "Tisch 23 [Ti23] Tisch 23 Fach a [a] Kiste 1 [K1]",
                              "Tisch 23 [Ti23] Fach b [b]"])
        finally:
            MigrationExecutor(connection).migrate(latest)
