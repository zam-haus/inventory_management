"""Production's path from label_printing 0003: label media become label material (0004–0006), the catalog is brought
up to date (0007), and back."""
import importlib

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

DEPLOYED = [("label_printing", "0003_location_display")]


class MigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_media_become_material_and_templates_their_successors(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        deployed = DEPLOYED + [node for node in latest if node[0] != "label_printing"]  # the other apps as they are
        try:
            apps = self.migrate(deployed)
            Stock, Medium = apps.get_model("label_printing", "LabelStock"), apps.get_model("label_printing", "LabelMedium")
            Printer, PrintJob = apps.get_model("label_printing", "Printer"), apps.get_model("label_printing", "PrintJob")
            Template, Rule = apps.get_model("inventory", "LocationLabelTemplate"), apps.get_model(
                "inventory", "LabelTemplateRule")
            # As 0002 and 0003 left them (other tests may have emptied the tables since)
            catalog = importlib.import_module("label_printing.migrations.0007_catalog_up_to_date")
            for old, _new in catalog.successions():
                if old and not Template.objects.filter(name=old["name"], label_width=old["label_width"],
                                                       label_height=old["label_height"]).exists():
                    template = Template.objects.create(**{field: old[field] for field in catalog.FIELDS})
                    Rule.objects.bulk_create([Rule(template=template, condition=condition, priority=priority)
                                              for condition, priority in old["rules"]])
            tape = Stock.objects.create(language="ptouch", name="TZe-231", tape_mm=12)
            Stock.objects.create(language="ptouch", name="TZe-631", tape_mm=12)
            labels = Stock.objects.create(language="zpl", name="57 × 32", width_mm=57, height_mm=32)
            zebra = Printer.objects.create(name="Zebra", slug="zebra", language="zpl")
            brother = Printer.objects.create(name="Brother", slug="brother", language="ptouch", model="P900W")
            used = Medium.objects.create(printer=zebra, stock=labels, zpl_darkness=5, quality="high", offset_x=10,
                                         is_default=True)
            own = Medium.objects.create(printer=zebra, name="Sonderformat", width_mm=40, height_mm=20)
            Medium.objects.create(printer=brother, stock=tape)
            Printer.objects.filter(pk=zebra.pk).update(loaded_medium=own)
            job = PrintJob.objects.create(printer=zebra, medium=used, layout_key="design:1")
            fixed = Template.objects.get(name="Fester Standort", label_width=70)
            edited = Template.objects.get(name="Fester Standort, Pfeil hoch")
            Template.objects.filter(pk=edited.pk).update(description=edited.description + "\n# edited")

            apps = self.migrate(latest)
            Stock = apps.get_model("label_printing", "LabelStock")
            Printer, PrintJob = apps.get_model("label_printing", "Printer"), apps.get_model("label_printing", "PrintJob")
            Template = apps.get_model("inventory", "LocationLabelTemplate")
            zebra = Printer.objects.get(pk=zebra.pk)
            own = Stock.objects.get(name="Sonderformat")
            self.assertEqual((zebra.offset_x, zebra.loaded_medium_id, PrintJob.objects.get(pk=job.pk).medium_id),
                             (10, own.pk, labels.pk))
            self.assertEqual(Stock.objects.filter(pk=labels.pk).values_list("zpl_darkness", "quality", "in_stock")[0],
                             (5, "high", True))
            self.assertEqual((own.language, own.width_mm, own.height_mm, own.in_stock), ("zpl", 40, 20, True))
            self.assertTrue(Stock.objects.get(pk=tape.pk).in_stock)  # on a printer: on hand
            self.assertTrue(Stock.objects.filter(language="ptouch", in_stock=False).exists())  # the other tapes not
            self.assertTrue(Stock.objects.filter(code="ERT-PG105X052Z1", in_stock=True).exists())
            self.assertEqual(apps.get_model("label_printing", "Ribbon").objects.count(), 6)
            self.assertEqual(Template.objects.get(pk=fixed.pk).name, "Lagermöbel")  # the same record, renamed
            self.assertTrue(Template.objects.get(pk=edited.pk).description.endswith("# edited"))  # left alone
            self.assertTrue(Template.objects.filter(name="Kabel, Fahne bis 10,5 mm (3G1,5)").exists())  # added

            apps = self.migrate(deployed)
            Template = apps.get_model("inventory", "LocationLabelTemplate")
            self.assertEqual(Template.objects.get(pk=fixed.pk).name, "Fester Standort")
            self.assertFalse(Template.objects.filter(name="Kabel, Fahne bis 10,5 mm (3G1,5)").exists())
        finally:
            self.migrate(latest)
