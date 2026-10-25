"""Which templates are meant for a subject and which comes first: the templates' rules (selection.py)."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.label_ids import services as label_ids
from inventory.models import Item, LabelId, LabelTemplateRule, LocationLabelTemplate, LocationType, UniqueItem
from .. import dialog, outcomes, selection, services
from ..design.texts import condition_error, holds
from ..label_urls import ItemAt
from ..models import LastLabel, PrintJob
from .helpers import SETTINGS, create_printers, create_user, generated
from .test_dialog import InventoryData


@override_settings(**SETTINGS)
class RuleTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        LocationLabelTemplate.objects.update(is_active=False)  # only those made here
        cls.box_type = LocationType.objects.create(name="Kiste", unique=True, category="container")
        cls.box = cls.part.__class__.objects.create(name="Kiste 1", short_name="K1", type=cls.box_type,
                                                    parent_location=cls.shelf)
        cls.mobile = cls.template("Mobil", [('location.type.category == "container"', 3)])
        cls.plain = cls.template("Schlicht", [("", 1)])
        cls.spare = cls.template("Reserve", [])  # no rules: every location, on request

    @classmethod
    def template(cls, name, rules, size="57 x 32"):
        template = LocationLabelTemplate.objects.create(name=name, description=f"label {size}\ntext {{{{ qr }}}}")
        LabelTemplateRule.objects.bulk_create([LabelTemplateRule(template=template, condition=condition,
                                                                 priority=priority) for condition, priority in rules])
        return template

    def ranked(self, subject):
        return [(entry.outcome.layout.template.name, entry.priority, entry.shown, entry.preselected)
                for entry in selection.rank(outcomes.outcomes("location"), "location", subject)]

    def test_the_highest_priority_first_priority_zero_on_request(self):
        self.assertEqual(self.ranked(self.box), [("Mobil", 3, True, True), ("Schlicht", 1, True, False),
                                                 ("Reserve", 0, False, False)])
        self.assertEqual(self.ranked(self.part), [("Schlicht", 1, True, True), ("Reserve", 0, False, False)])
        # Priority 0 is shown when nothing ranks higher
        LabelTemplateRule.objects.filter(template=self.plain).update(priority=0)
        self.assertEqual(self.ranked(self.part), [("Reserve", 0, True, True), ("Schlicht", 0, True, False)])  # by name

    def test_the_last_label_of_a_location_comes_first(self):
        selection.remember_label(self.box, self.spare)
        self.assertEqual(self.ranked(self.box)[0], ("Reserve", 0, True, True))
        self.assertEqual(selection.preferred_template("location", self.box), self.spare)
        with patch("label_printing.services.process"):
            job = services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{self.plain.pk}",
                                  subject_type="location", subjects=[self.box])
        PrintJob.objects.filter(pk=job.pk).update(status=PrintJob.Status.DONE)
        selection.remember_job(PrintJob.objects.get(pk=job.pk))
        self.assertEqual(LastLabel.objects.get(subject_pk=str(self.box.pk)).layout_key, f"design:{self.plain.pk}")
        # The admin's print actions take it too
        self.assertEqual(services.location_layout(self.box, self.zebra, self.labels).template, self.plain)

    def test_printable_templates_first_among_equals(self):
        on_tape = self.template("Schlicht", [("", 1)], size="height 12")
        LabelTemplateRule.objects.filter(template=self.plain).update(priority=1)
        self.brother.remember_status({"ok": True, "errors": [], "media_width_mm": 24})  # 12 mm tape not loaded
        names = [(entry.outcome.layout.template.pk, entry.outcome.target() is not None)
                 for entry in selection.rank(outcomes.outcomes("location"), "location", self.part)]
        self.assertEqual(names[:2], [(self.plain.pk, True), (on_tape.pk, False)])

    def test_conditions(self):
        self.assertIsNone(condition_error('location.type.category == "container" and location.name'))
        self.assertIn("Unexpected end of expression", condition_error("location.name =="))
        self.assertEqual(condition_error("{% if x %}"), "Write the condition alone, without {% if %}.")
        self.assertTrue(holds("", {}))
        self.assertFalse(holds("location.unknown.deeper", {"location": self.part}))


@override_settings(**SETTINGS)
class SubjectsTests(InventoryData, TestCase):
    """The templates made by the migrations, with their rules."""

    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.user = create_user("printing", "label_printing.print_label")

    def first(self, subject_type, subject):
        found = [outcome for kind in selection.KINDS[subject_type] for outcome in outcomes.outcomes(kind)]
        ranked = selection.rank(found, subject_type, subject)
        return ranked[0].outcome.layout.template if ranked else None

    def test_items_for_sale_get_price_tags_unique_ones_nothing(self):
        on_tape = generated("item", "tape12")
        LocationLabelTemplate.objects.filter(subject_type="item").exclude(label_width=None).update(is_active=False)
        self.assertEqual(self.first("item", ItemAt(self.item, self.part)).name, "Preisschild")
        Item.objects.filter(pk=self.item.pk).update(for_sale=False, sale_price=None)
        self.item.refresh_from_db()
        self.assertEqual(self.first("item", ItemAt(self.item, self.part)), on_tape)
        drill = Item.objects.create(name="Bohrmaschine", kind=Item.Kind.UNIQUE, measurement_unit=self.unit)
        self.assertIsNone(self.first("item", ItemAt(drill, None)))
        self.assertEqual(dialog.unavailable_reason("item", dialog.options("item", drill)),
                         "No label template is meant for this.")

    def test_unique_items_with_an_owner_get_the_owner_on_the_label(self):
        drill = UniqueItem.objects.create(item=Item.objects.create(name="Bohrmaschine", kind=Item.Kind.UNIQUE),
                                          location=self.part)
        self.assertEqual(self.first("uniqueitem", drill).subject_type, "labelid")  # ZAMid, by its label ID
        drill.owner_first_name = "Robin"
        self.assertEqual(self.first("uniqueitem", drill).name, "ZAMid mit Eigentum")
        drill.save()
        # Printed with a label ID template, it gets its label ID now
        self.client.force_login(self.user)
        zamid = next(outcome for outcome in outcomes.outcomes("labelid")
                     if outcome.layout.template == generated("labelid", "57x32"))
        with self.captureOnCommitCallbacks(execute=True), patch("label_printing.services.process"):
            response = self.client.post(reverse("print_labels", args=["uniqueitem", drill.pk]),
                                        {"outcome": zamid.key, "copies": 1}, headers={"Accept": "application/json"})
        job = PrintJob.objects.get(pk=response.json()["job"]["id"])
        lid = LabelId.objects.get(unique_item=drill)
        self.assertEqual((job.subject_type, job.label_code), ("labelid", lid.code))
        # With the owner's template: the unique item, with its owner
        owned = next(outcome for outcome in outcomes.outcomes("uniqueitem")
                     if outcome.layout.template.label_width == 57)
        with patch("label_printing.services.process"):
            response = self.client.post(reverse("print_labels", args=["uniqueitem", drill.pk]),
                                        {"outcome": owned.key, "copies": 1}, headers={"Accept": "application/json"})
        job = PrintJob.objects.get(pk=response.json()["job"]["id"])
        self.assertEqual((job.subject_type, job.snapshot[0]["owner"], job.label_code), ("uniqueitem", "Robin", lid.code))

    def test_a_label_id_of_a_unique_item_marked_printed(self):
        drill = UniqueItem.objects.create(item=Item.objects.create(name="Bohrmaschine", kind=Item.Kind.UNIQUE),
                                          location=self.part, owner_first_name="Robin")
        lid = label_ids.generate_and_claim(drill, None)
        owned = next(outcome for outcome in outcomes.outcomes("uniqueitem")
                     if outcome.layout.template.label_width == 57)
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=owned.layout.key,
                              subject_type="uniqueitem", subjects=[drill])
        PrintJob.objects.filter(pk=job.pk).update(status=PrintJob.Status.PROCESSING)
        services.finish(PrintJob.objects.get(pk=job.pk), services.Result("done", printer_status={"ok": True,
                                                                                                  "errors": []}))
        lid.refresh_from_db()
        self.assertIsNotNone(lid.printed_at)
