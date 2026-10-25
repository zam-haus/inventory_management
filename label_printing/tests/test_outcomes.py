"""The print dialog offers labels (outcomes), not printers; a label no printer can print now may wait for one."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventory.models import LocationLabelTemplate
from .. import dialog, outcomes, services
from ..devices.run import DONE, Result
from ..models import LabelMedium, PrintAgent, Printer, PrintJob
from .helpers import SETTINGS, create_printers, create_user, outcome_key
from .test_dialog import InventoryData

TAPE_24 = {"ok": True, "errors": [], "media_width_mm": 24}
TAPE_12 = {"ok": True, "errors": [], "media_width_mm": 12}


@override_settings(**SETTINGS)
class OutcomeTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.on_tape, cls.on_labels = outcome_key("location", "tape12"), outcome_key("location", "57x32")
        cls.template = LocationLabelTemplate.objects.create(name="Fach", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        cls.user = create_user("printing", "label_printing.print_label")

    def found(self, subject_type="location"):
        return {outcome.key: outcome for outcome in outcomes.outcomes(subject_type)}

    def test_labels_instead_of_printers(self):
        found = self.found()
        self.assertEqual(list(found)[0], f"design:{self.template.pk}@57x32")  # templates first
        self.assertIn(self.on_tape, found)
        self.assertEqual((found[self.on_tape].target().printer, found[self.on_tape].size), (self.brother, "12 mm tape"))
        self.assertEqual(found[self.on_labels].size, "57 × 32 mm labels")

    def test_greyed_with_the_reason(self):
        Printer.objects.filter(pk=self.zebra.pk).update(is_active=False)
        self.brother.remember_status(TAPE_24)
        found = self.found()
        self.assertNotIn(self.on_labels, found)  # inactive printers offer nothing
        tape = found[self.on_tape]
        self.assertEqual((tape.target(), tape.why_not, tape.can_wait), (None, "Loaded: 24 mm tape.", True))
        # A template for labels no printer has: shown, not printable now; it may wait for the labels to be put in
        template = found[f"design:{self.template.pk}"]
        self.assertEqual((template.why_not, template.can_wait), ("No printer has labels of this size.", True))
        options = dialog.options("location", self.part)
        item = next(item for item in options["outcomes"] if item["key"] == self.on_tape)
        self.assertEqual((item["printer"], item["reason"], item["can_wait"]), ("", "Loaded: 24 mm tape.", True))
        self.assertIn(f"medium={self.tape.pk}", item["preview"])  # previewed as it would print
        self.assertEqual(dialog.unavailable_reason(options), "")  # the dialog opens: labels may wait

    def test_the_printer_that_can_print_is_chosen(self):
        other = Printer.objects.create(name="P-touch Lager", slug="ptouch2", language="ptouch", model="E550W", dpi=180,
                                       host="127.0.0.1", is_default=True)
        LabelMedium.objects.create(printer=other, name="12 mm", ptouch_tape=12)
        self.assertEqual(self.found()[self.on_tape].target().printer, other)  # the default printer first
        other.remember_status(TAPE_24)
        self.assertEqual(self.found()[self.on_tape].target().printer, self.brother)
        Printer.objects.filter(pk=self.brother.pk).update(last_status={"ok": False, "errors": ["cover_open"]})
        self.assertEqual(self.found()[self.on_tape].why_not, "Loaded: 24 mm tape.")

    def test_zebras_print_on_the_labels_set_as_loaded(self):
        other = LabelMedium.objects.create(printer=self.zebra, name="60 × 30 mm", width_mm=60, height_mm=30)
        on_other = outcome_key("location", "60x30")
        found = self.found()
        self.assertEqual(found[self.on_labels].target().printer, self.zebra)
        self.assertEqual((found[on_other].why_not, found[on_other].can_wait), ("Loaded: 57 × 32 mm.", True))
        # It measured labels of another length: those set as loaded are not in it.
        self.zebra.remember_status({"ok": True, "errors": [], "label_length_dots": 200})  # 25 mm at 203 dpi
        self.assertEqual(self.found()[self.on_labels].why_not,
                         "The printer measures labels 25 mm long, but labels 32 mm high are set as loaded.")
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_medium=other)  # 60 × 30 mm put in
        self.zebra.remember_status({"ok": True, "errors": [], "label_length_dots": 240})
        self.assertEqual(self.found()[on_other].target().medium, other)
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_medium=None)
        self.assertEqual(self.found()[self.on_labels].why_not,
                         "No labels are set as loaded in this printer (admin: its settings).")
        self.assertEqual(services.default_medium(Printer.objects.get(pk=self.zebra.pk)), self.labels)

    def test_inactive_templates_are_neither_offered_nor_printed(self):
        LocationLabelTemplate.objects.filter(pk=self.template.pk).update(is_active=False)
        self.assertNotIn(f"design:{self.template.pk}@57x32", self.found())
        with self.assertRaises(services.PrintError):
            services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{self.template.pk}",
                            subject_type="location", subjects=[self.part])
        LocationLabelTemplate.objects.update(is_active=False)
        self.assertEqual(self.found(), {})

    def test_nothing_set_up(self):
        Printer.objects.all().delete()
        LocationLabelTemplate.objects.all().delete()
        self.assertEqual(dialog.unavailable_reason(dialog.options("location", self.part)),
                         "No printer is set up for these labels yet.")


@override_settings(**SETTINGS)
class WaitingTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.on_tape, cls.on_labels = outcome_key("location", "tape12"), outcome_key("location", "57x32")
        cls.user = create_user("printing", "label_printing.print_label")

    def setUp(self):
        self.client.force_login(self.user)
        # Network printers are asked for their status while jobs wait; here they answer as set in self.status.
        self.status = TAPE_24
        patcher = patch("label_printing.services.query_status", side_effect=lambda device, language: Result(
            DONE, printer_status=self.status))
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("print_labels", args=["location", self.part.pk]), data,
                                    headers={"Accept": "application/json"})

    def test_waits_until_the_right_tape_is_loaded(self):
        self.brother.remember_status(TAPE_24)
        data = self.post({"outcome": self.on_tape, "copies": 1}).json()  # no printer can print it now: it waits
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.status, job.printer, job.payload, job.outcome), ("waiting", None, None, self.on_tape))
        self.assertTrue(data["job"]["message"].startswith("Waiting for a printer that can print it, until "))
        url = reverse("print_job_status", args=[job.pk])
        # The dialog asks …
        Printer.objects.filter(pk=self.brother.pk).update(last_status_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(url).json()["status"], "waiting")  # still 24 mm
        self.status = TAPE_12  # … and the tape is changed
        Printer.objects.filter(pk=self.brother.pk).update(last_status_at=timezone.now() - timedelta(minutes=1))
        with patch("label_printing.services.process") as process, self.captureOnCommitCallbacks(execute=True):
            status = self.client.get(url).json()
        job.refresh_from_db()
        self.assertEqual((job.status, job.printer, job.medium, job.snapshot[0]["code"]),
                         ("pending", self.brother, self.tape, "R303.a"))
        self.assertTrue(bytes(job.payload))
        process.assert_called_once_with(job.pk)
        self.assertEqual(status["printer"], "P-touch Werkstatt")

    def test_printer_on_an_agent_coming_back(self):
        agent = PrintAgent(name="pi", is_active=True)
        token = agent.new_token()
        agent.last_seen = timezone.now() - timedelta(hours=1)
        agent.save()
        printer = Printer.objects.create(name="USB", slug="usb", uid="usb-1", language="zpl", dpi=203,
                                         transport="agent", agent=agent)
        printer.loaded_medium = LabelMedium.objects.create(printer=printer, name="60 × 30", width_mm=60, height_mm=30)
        printer.save()
        found = {outcome.key: outcome for outcome in outcomes.outcomes("location")}
        on_usb = outcome_key("location", "60x30")
        self.assertEqual(found[on_usb].why_not, "The print agent of this printer is offline.")
        job = services.submit_outcome(found[on_usb], subject_type="location", subjects=[self.part],
                                      user=self.user, wait=True)
        self.assertEqual(job.status, "waiting")
        answer = self.client.post(reverse("print_agent_poll"), {}, content_type="application/json",
                                  headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(answer["job"]["id"], job.pk)  # back: the job is drawn for it and handed over at once
        job.refresh_from_db()
        self.assertEqual((job.status, job.printer), ("processing", printer))

    def test_expires_unprinted(self):
        self.brother.remember_status(TAPE_24)
        found = {outcome.key: outcome for outcome in outcomes.outcomes("location")}
        job = services.submit_outcome(found[self.on_tape], subject_type="location", subjects=[self.part],
                                      user=self.user, wait=True)
        PrintJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        status = self.client.get(reverse("print_job_status", args=[job.pk])).json()
        self.assertEqual((status["status"], status["finished"], status["message"]),
                         ("expired", True, "No printer could print it in time, so it was not printed."))

    def test_waits_for_labels_no_printer_has_yet(self):
        template = LocationLabelTemplate.objects.create(name="Groß", description="label 100 x 50\ntext {{ location.unique_identifier }}")
        data = self.post({"outcome": f"design:{template.pk}", "copies": 1}).json()
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.status, job.outcome), ("waiting", f"design:{template.pk}"))
        # The labels are put into the Zebra and set as loaded there
        large = LabelMedium.objects.create(printer=self.zebra, name="100 × 50 mm", width_mm=100, height_mm=50)
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_medium=large, last_status=None)
        with patch("label_printing.services.process"), self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse("print_job_status", args=[job.pk]))
        job.refresh_from_db()
        self.assertEqual((job.status, job.printer, job.medium), ("pending", self.zebra, large))

    def test_without_active_printers_nothing_waits(self):
        template = LocationLabelTemplate.objects.create(name="Groß", description="label 100 x 50\ntext {{ location.unique_identifier }}")
        Printer.objects.update(is_active=False)
        response = self.post({"outcome": f"design:{template.pk}", "copies": 1})
        self.assertEqual(response.json()["errors"]["outcome"][0]["message"], "No printer has labels of this size.")
        self.assertFalse(PrintJob.objects.exists())

    def test_with_a_broker_one_task_looks_again_and_again(self):
        from django.core.cache import cache
        cache.delete("label_printing:dispatch_scheduled")
        self.brother.remember_status(TAPE_24)
        outcome = {outcome.key: outcome for outcome in outcomes.outcomes("location")}[self.on_tape]
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False), \
                patch("label_printing.tasks.dispatch_waiting_jobs.apply_async") as schedule, \
                self.captureOnCommitCallbacks(execute=True):
            for _job in range(2):
                services.submit_outcome(outcome, subject_type="location", subjects=[self.part], wait=True)
        schedule.assert_called_once_with(countdown=services.DISPATCH_EVERY)

    def test_templates_print_in_their_quality(self):
        template = LocationLabelTemplate.objects.create(name="Fein", quality="draft", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        with patch("label_printing.services.process"):
            data = self.post({"outcome": f"design:{template.pk}@57x32", "copies": 1}).json()
        self.assertEqual(PrintJob.objects.get(pk=data["job"]["id"]).quality, "draft")
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{template.pk}",
                              subject_type="location", subjects=[self.part])  # the admin's print actions too
        self.assertEqual(job.quality, "draft")

    def test_printable_labels_print_at_once(self):
        with patch("label_printing.services.process"):
            data = self.post({"outcome": self.on_labels, "copies": 1}).json()
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.status, job.printer), ("pending", self.zebra))
