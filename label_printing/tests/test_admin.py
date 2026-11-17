from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import LabelStock, Printer, PrintJob
from .helpers import SETTINGS, SimulatedPrinters, create_printers


@override_settings(**SETTINGS)
class PrinterValidationTests(TestCase):
    def test_brother_needs_a_known_model_and_gets_its_resolution(self):
        printer = Printer(name="P", slug="p", language="ptouch", model="QL-800", host="h")
        with self.assertRaises(ValidationError) as raised:
            printer.clean()
        self.assertIn("model", raised.exception.message_dict)
        printer.model = "P900W"
        printer.clean()
        self.assertEqual(printer.dpi, 360)

    def test_connection_needs_host_or_agent(self):
        for transport, field in (("network", "host"), ("agent", "agent")):
            with self.subTest(transport=transport), self.assertRaises(ValidationError) as raised:
                Printer(name="Z", slug="z", language="zpl", transport=transport).clean()
            self.assertIn(field, raised.exception.message_dict)

    def test_label_material_needs_its_size(self):
        with self.assertRaises(ValidationError) as raised:
            LabelStock(language="zpl", name="x").clean()
        self.assertEqual(set(raised.exception.message_dict), {"width_mm", "height_mm"})
        with self.assertRaises(ValidationError) as raised:
            LabelStock(language="ptouch", name="x").clean()
        self.assertIn("tape_mm", raised.exception.message_dict)

    def test_what_a_printer_takes_comes_from_its_model(self):
        gk420t = Printer.objects.create(name="GK", slug="gk", language="zpl", model="GK420t-200dpi", host="h")
        self.assertEqual((gk420t.max_width_mm, gk420t.core_mm, gk420t.winding, gk420t.thermal_transfer),
                         (108, Decimal("25.4"), "outside", True))
        label = dict(language="zpl", name="L", width_mm=70, height_mm=32, core_mm=Decimal("25.4"), winding="outside",
                     method="transfer", ribbon="wax")
        self.assertEqual(gk420t.takes(LabelStock(**label)), "")
        self.assertEqual(gk420t.takes(LabelStock(**{**label, "width_mm": 110})),
                         "The labels are wider than the printer takes (108 mm).")
        self.assertEqual(gk420t.takes(LabelStock(**{**label, "core_mm": Decimal("76.2")})),
                         "The roll core (76.2 mm) does not fit the printer (25.4 mm).")
        self.assertEqual(gk420t.takes(LabelStock(**{**label, "winding": "inside"})),
                         "The labels are wound inside, the printer takes them outside.")
        self.assertEqual(gk420t.takes(LabelStock(**{**label, "core_mm": None, "winding": ""})), "")  # not known
        gk420d = Printer.objects.create(name="GKd", slug="gkd", language="zpl", model="GK420d", host="h")
        self.assertEqual(gk420d.takes(LabelStock(**label)),
                         "These labels need a ribbon, the printer prints direct thermal only.")
        self.assertEqual(gk420d.takes(LabelStock(**{**label, "method": "direct", "ribbon": ""})), "")
        gk420d.model = "GK420t"  # another model is another printer
        with self.assertRaises(ValidationError) as raised:
            gk420d.clean()
        self.assertIn("model", raised.exception.message_dict)
        given = Printer.objects.create(name="GKt", slug="gkt", language="zpl", model="GK420t", host="h",
                                       thermal_transfer=False, max_width_mm=104)
        self.assertEqual((given.thermal_transfer, given.max_width_mm, given.core_mm), (False, 104, Decimal("25.4")))
        e550w = Printer.objects.create(name="E", slug="e", language="ptouch", model="E550W", host="h")
        self.assertEqual(e550w.max_width_mm, 24)
        self.assertEqual(e550w.takes(LabelStock(language="ptouch", name="T", tape_mm=36)),
                         "The printer does not take 36 mm tape.")
        self.assertEqual(e550w.takes(LabelStock(language="ptouch", name="T", tape_mm=24)), "")
        self.assertEqual(e550w.takes(LabelStock(**label)), "These labels are for another kind of printer.")

    def test_loaded_labels_are_ones_the_printer_takes(self):
        zebra, labels, brother, tape = create_printers()
        zebra.loaded_medium = tape.stock
        with self.assertRaises(ValidationError) as raised:
            zebra.clean()
        self.assertIn("loaded_medium", raised.exception.message_dict)

    def test_one_default_printer(self):
        zebra, labels, brother, tape = create_printers()
        brother.is_default = True
        brother.save()
        self.assertEqual(list(Printer.objects.filter(is_default=True)), [brother])

    def test_material_on_hand_is_offered(self):
        zebra, on_hand, brother, tape = create_printers()
        other = LabelStock.objects.create(language="zpl", name="100 × 50", width_mm=100, height_mm=50)
        self.assertNotIn(other, [medium.stock for medium in zebra.media()])
        self.assertIn(other, [medium.stock for medium in zebra.media(in_stock=False)])
        self.assertEqual([medium.stock for medium in brother.media()], [tape.stock])


@override_settings(**SETTINGS)
class PrinterAdminTests(SimulatedPrinters, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="pw")
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers(cls.zebra_server.port, cls.brother_server.port)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def action(self, action, *printers):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("admin:label_printing_printer_changelist"), {
                "action": action, "_selected_action": [printer.pk for printer in printers]}, follow=True)

    def test_test_print(self):
        # Queued in the test's transaction; printed once it commits (at once outside of tests, without a broker).
        response = self.action("test_print", self.zebra, self.brother)
        self.assertContains(response, "Zebra Lager: test label waiting")
        self.assertContains(response, "P-touch Werkstatt: test label waiting")
        self.assertEqual(PrintJob.objects.filter(status="done", layout_key="test").count(), 2)
        self.assertEqual(len(self.brother_output.printed), 1)

    def test_calibration_label(self):
        response = self.action("calibration_print", self.brother)
        self.assertContains(response, "P-touch Werkstatt: calibration label waiting")
        job = PrintJob.objects.get()
        self.assertEqual((job.layout_key, job.snapshot[0]["rows"]), ("calibration", 70))

    def test_printer_without_material_on_hand_says_so(self):
        LabelStock.objects.filter(pk=self.tape.pk).update(in_stock=False)
        response = self.action("test_print", self.brother)
        self.assertContains(response, "P-touch Werkstatt: It takes no label material on hand. Mark label material as "
                                      "on hand (Label material)")
        self.assertFalse(PrintJob.objects.exists())

    def test_loaded_tape_prints_without_being_on_hand(self):
        LabelStock.objects.filter(pk=self.tape.pk).update(in_stock=False)
        self.action("check_status", self.brother)  # reports 12 mm tape
        response = self.action("test_print", self.brother)
        self.assertContains(response, "P-touch Werkstatt: test label waiting")
        self.assertEqual(PrintJob.objects.get().medium.tape_mm, 12)

    def test_tape_missing_from_the_catalog_is_added_once_reported(self):
        LabelStock.objects.filter(tape_mm=24).delete()
        self.brother_state.tape_mm = 24
        self.action("check_status", self.brother)
        self.action("check_status", self.brother)
        tape = LabelStock.objects.get(tape_mm=24)
        self.assertEqual((tape.name, tape.in_stock, tape.background_color, tape.print_color),
                         ("24 mm", False, "weiß", "schwarz"))
        self.action("calibration_print", self.brother)
        self.assertEqual(PrintJob.objects.get().medium, tape)

    def test_check_status(self):
        self.brother_state.errors = ["cover_open"]
        response = self.action("check_status", self.brother)
        self.assertContains(response, "P-touch Werkstatt: The cover is open.")

    def test_changelist_and_job_log(self):
        self.action("test_print", self.zebra)
        self.assertContains(self.client.get(reverse("admin:label_printing_printer_changelist")), "Ready.")
        response = self.client.get(reverse("admin:label_printing_printjob_changelist"))
        self.assertContains(response, "Zebra Lager")
        job = PrintJob.objects.get()
        self.assertEqual(self.client.get(reverse("admin:label_printing_printjob_change", args=[job.pk])).status_code, 200)

    def test_loaded_labels_offer_the_printers_own(self):
        response = self.client.get(reverse("admin:label_printing_printer_change", args=[self.zebra.pk]))
        choices = list(response.context["adminform"].form.fields["loaded_medium"].queryset)
        self.assertIn(self.labels.stock, choices)
        self.assertNotIn(self.tape.stock, choices)  # a Brother tape
        self.assertContains(response, "57 × 32 mm")  # the material on hand it takes

