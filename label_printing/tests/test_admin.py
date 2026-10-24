from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import LabelMedium, PrintAgent, Printer, PrintJob
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

    def test_media_fit_their_printer(self):
        zebra, _labels, brother, _tape = create_printers()
        with self.assertRaises(ValidationError) as raised:
            LabelMedium(printer=zebra, name="x").clean()
        self.assertEqual(set(raised.exception.message_dict), {"width_mm", "height_mm"})
        with self.assertRaises(ValidationError) as raised:
            LabelMedium(printer=brother, name="x", ptouch_tape=36).clean()  # the E550W takes up to 24 mm
        self.assertIn("ptouch_tape", raised.exception.message_dict)

    def test_loaded_labels_are_the_printers_own(self):
        zebra, labels, brother, tape = create_printers()
        zebra.loaded_medium = tape
        with self.assertRaises(ValidationError) as raised:
            zebra.clean()
        self.assertIn("loaded_medium", raised.exception.message_dict)

    def test_one_default_printer_and_medium(self):
        zebra, labels, brother, tape = create_printers()
        brother.is_default = True
        brother.save()
        self.assertEqual(list(Printer.objects.filter(is_default=True)), [brother])
        second = LabelMedium.objects.create(printer=zebra, name="100 × 50", width_mm=100, height_mm=50, is_default=True)
        self.assertEqual(list(zebra.media.filter(is_default=True)), [second])


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
        self.assertEqual(choices, [self.labels])

    def test_agent_token_is_shown_once(self):
        response = self.client.post(reverse("admin:label_printing_printagent_add"), {"name": "pi-lager"}, follow=True)
        agent = PrintAgent.objects.get(name="pi-lager")
        token = response.content.decode().split("<code>")[1].split("</code>")[0]
        self.assertEqual(PrintAgent.for_token(token), agent)
        self.client.post(reverse("admin:label_printing_printagent_changelist"),
                         {"action": "new_token", "_selected_action": [agent.pk]})
        self.assertIsNone(PrintAgent.for_token(token))
