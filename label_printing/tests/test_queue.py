from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.groups import local_group_name
from inventory.models import Location, LocationLabelTemplate, LocationType
from .. import services
from ..devices.run import Result
from ..models import LabelMedium, PrintAgent, Printer, PrintJob
from .helpers import SETTINGS, SimulatedPrinters, create_printers, create_user


@override_settings(**SETTINGS)
class SubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.user = create_user()

    def submit(self, printer=None, medium=None, **kwargs):
        options = dict(printer=printer or self.zebra, medium=medium or self.labels, layout_key="test",
                       subject_type="printer", subjects=[printer or self.zebra], user=self.user)
        return services.submit(**{**options, **kwargs})

    def test_zebra_job_holds_a_raster_format_per_label(self):
        job = self.submit(copies=3)
        self.assertEqual((job.status, job.pages, job.copies, job.user), ("pending", 3, 3, self.user))
        zpl = bytes(job.payload).decode()
        self.assertTrue(zpl.startswith("^XA^PW456^LL256^LH0,0^FO0,0^GFA,"))
        self.assertTrue(zpl.endswith("^PQ3^XZ"))
        self.assertEqual(job.snapshot, [{"printer": "Zebra Lager", "medium": "57 × 32 mm"}])

    def test_brother_job_is_ptouch_raster(self):
        job = self.submit(self.brother, self.tape, copies=2)
        self.assertEqual(job.pages, 2)
        self.assertTrue(bytes(job.payload).startswith(b"\x00" * 200 + b"\x1b@"))

    def test_network_jobs_go_to_the_worker_after_commit(self):
        with patch("label_printing.tasks.process_job.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            job = self.submit()
        delay.assert_called_once_with(job.pk)

    def test_agent_jobs_wait_for_the_agent(self):
        agent = PrintAgent(name="pi")
        agent.new_token()
        agent.last_seen = timezone.now()
        agent.save()
        Printer.objects.filter(pk=self.zebra.pk).update(transport="agent", agent=agent, host="")
        self.zebra.refresh_from_db()
        with patch("label_printing.tasks.process_job.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            self.submit()
        delay.assert_not_called()

    def test_same_request_id_gives_the_same_job(self):
        request_id = uuid4()
        first = self.submit(request_id=request_id)
        self.assertEqual(self.submit(request_id=request_id), first)
        self.assertEqual(PrintJob.objects.count(), 1)

    def test_refusals(self):
        cases = [
            (dict(medium=self.tape), "Choose a label medium of this printer."),
            (dict(copies=0), "Print between 1 and 20 copies."),
            (dict(copies=21), "Print between 1 and 20 copies."),
            (dict(layout_key="nope"), "Unknown layout."),
            (dict(subject_type="location"), "This layout does not fit the chosen printer and medium."),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesMessage(services.PrintError, message):
                self.submit(**kwargs)
        Printer.objects.filter(pk=self.zebra.pk).update(is_active=False)
        self.zebra.refresh_from_db()
        with self.assertRaisesMessage(services.PrintError, "The printer is switched off in the admin."):
            self.submit()

    def test_offline_agent_refuses_jobs(self):
        agent = PrintAgent(name="pi")
        agent.new_token()
        agent.save()
        printer = Printer.objects.create(name="USB", slug="usb", language="zpl", transport="agent", agent=agent)
        medium = LabelMedium.objects.create(printer=printer, name="L", width_mm=50, height_mm=30)
        with self.assertRaisesMessage(services.PrintError, "The print agent of this printer is offline."):
            self.submit(printer, medium, subjects=[printer])

    def test_label_templates_print_on_media_of_their_size(self):
        def template(name, size="57 x 32"):
            return LocationLabelTemplate.objects.create(name=name, description=f"label {size}\nrow\n  qr {{qr}}\n  text {{code}}")
        fitting, wide = template("Fach"), template("Breit", "70 x 32")
        kind = LocationType.objects.create(name="Room", unique=True)
        location = Location.objects.create(name="Lager", short_name="WH", type=kind)
        options = dict(subject_type="location", subjects=[location])
        with self.assertRaises(services.PrintError):
            self.submit(layout_key=f"design:{wide.pk}", **options)
        job = self.submit(copies=2, layout_key=f"design:{fitting.pk}", **options)
        payload = bytes(job.payload).decode()
        self.assertTrue(payload.startswith("^XA^PW456^LL256") and "^GFA" in payload and "^PQ2" in payload)
        self.assertEqual((job.label_code, job.subject_label, job.subject_id), ("WH", str(location), location.pk))
        self.assertEqual(job.snapshot[0]["code"], "WH")
        # Templates chosen for the medium: only those.
        self.labels.label_templates.add(template("Gewählt"))
        with self.assertRaises(services.PrintError):
            self.submit(layout_key=f"design:{fitting.pk}", **options)


@override_settings(**SETTINGS)
class QueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()

    def job(self, **fields):
        return PrintJob.objects.create(printer=self.zebra, medium=self.labels, layout_key="test",
                                       subject_type="printer", payload=b"^XA^XZ", **fields)

    def test_a_job_is_claimed_once(self):
        job = self.job()
        self.assertTrue(services.claim(job.pk, "worker"))
        self.assertFalse(services.claim(job.pk, "other"))
        job.refresh_from_db()
        self.assertEqual((job.status, job.claimed_by), ("processing", "worker"))

    def test_stale_jobs_expire_and_lost_ones_fail(self):
        old = timezone.now() - timedelta(seconds=200)
        waiting, lost, fresh = self.job(), self.job(status="processing"), self.job()
        PrintJob.objects.filter(pk=waiting.pk).update(created_at=old)
        PrintJob.objects.filter(pk=lost.pk).update(claimed_at=old)
        self.assertFalse(services.claim(waiting.pk, "worker"))
        services.expire_stale()
        statuses = dict(PrintJob.objects.values_list("pk", "status"))
        self.assertEqual((statuses[waiting.pk], statuses[lost.pk], statuses[fresh.pk]), ("expired", "failed", "pending"))
        self.assertEqual(PrintJob.objects.get(pk=lost.pk).message, "The print worker or agent did not report back.")
        self.assertIsNone(PrintJob.objects.get(pk=waiting.pk).payload)

    def test_finish_records_the_result_and_the_printer_status(self):
        job = self.job()
        services.claim(job.pk, "worker")
        status = {"language": "zpl", "errors": ["paper_out"], "ok": False}
        job = services.finish(job, Result("failed", "paper_out", printer_status=status))
        self.assertEqual((job.status, job.code, job.message), ("failed", "paper_out", "The printer is out of labels."))
        self.assertIsNone(job.payload)
        self.zebra.refresh_from_db()
        self.assertEqual(self.zebra.last_status, status)
        self.assertEqual(self.zebra.status_text, "The printer is out of labels.")

    def test_wrong_tape_message(self):
        job = self.job(status="failed", code="wrong_tape", detail={"loaded_mm": 24, "expected_mm": 12})
        self.assertEqual(job.message, "24 mm tape is loaded, but 12 mm was chosen.")

    def test_agent_gets_the_oldest_job_of_its_printers(self):
        agent = PrintAgent(name="pi")
        agent.new_token()
        agent.save()
        Printer.objects.filter(pk=self.zebra.pk).update(transport="agent", agent=agent)
        older, newer = self.job(), self.job()
        PrintJob.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(seconds=10))
        other = PrintJob.objects.create(printer=self.brother, medium=self.tape, layout_key="test",
                                        subject_type="printer", payload=b"x")
        self.assertEqual(services.next_for_agent(agent), older)
        self.assertEqual(services.next_for_agent(agent), newer)
        self.assertIsNone(services.next_for_agent(agent))
        self.assertEqual(PrintJob.objects.get(pk=other.pk).status, "pending")
        self.assertEqual(PrintJob.objects.get(pk=older.pk).agent, agent)


@override_settings(**SETTINGS)
class NetworkPrintingTests(SimulatedPrinters, TestCase):
    """Without a broker the worker's task runs right away, against the fake printers."""

    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers(cls.zebra_server.port, cls.brother_server.port)

    def print_test_label(self, printer, medium):
        with self.captureOnCommitCallbacks(execute=True):
            job = services.submit(printer=printer, medium=medium, layout_key="test", subject_type="printer",
                                  subjects=[printer])
        job.refresh_from_db()
        return job

    def test_zebra(self):
        job = self.print_test_label(self.zebra, self.labels)
        self.assertEqual((job.status, job.claimed_by), ("done", "worker"))
        self.assertEqual(len(self.zebra_output.printed), 1)

    def test_brother(self):
        job = self.print_test_label(self.brother, self.tape)
        self.assertEqual(job.status, "done")
        self.assertEqual(len(self.brother_output.printed), 1)
        self.brother.refresh_from_db()
        self.assertEqual(self.brother.status_text, "Ready. Loaded: 12 mm tape, schwarz on weiß.")

    def test_wrong_tape(self):
        self.brother_state.tape_mm = 24
        job = self.print_test_label(self.brother, self.tape)
        self.assertEqual((job.status, job.message), ("failed", "24 mm tape is loaded, but 12 mm was chosen."))

    def test_unreachable_printer_is_tried_again_then_fails(self):
        port = self.zebra_server.port
        Printer.objects.filter(pk=self.zebra.pk).update(port=1)
        self.zebra.refresh_from_db()
        with patch("label_printing.services.time.sleep") as sleep:
            job = self.print_test_label(self.zebra, self.labels)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual((job.status, job.code), ("failed", "unreachable"))
        self.assertNotEqual(port, 1)

    def test_check_status(self):
        self.zebra_state.errors = ["paused"]
        result = services.check_status(self.zebra)
        self.assertEqual(result.printer_status["errors"], ["paused"])
        self.zebra.refresh_from_db()
        self.assertEqual(self.zebra.status_text, "The printer is paused; press its pause button.")


@override_settings(**SETTINGS)
class JobStatusViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, *_ = create_printers()
        cls.user = create_user("owner")
        cls.other = create_user("other")
        cls.job = PrintJob.objects.create(printer=cls.zebra, medium=cls.labels, layout_key="test", user=cls.user,
                                          subject_type="printer", status="failed", code="paper_out")

    def test_owner_sees_the_job(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("print_job_status", args=[self.job.pk]))
        self.assertEqual(response.json(), {"id": self.job.pk, "status": "failed", "finished": True, "ok": False,
                                           "message": "The printer is out of labels."})

    def test_others_do_not(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("print_job_status", args=[self.job.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("print_job_status", args=[self.job.pk])).status_code, 302)


class PermissionMigrationTests(TestCase):
    def test_local_group_may_print_labels(self):
        group = Group.objects.get(name=local_group_name())
        self.assertTrue(group.permissions.filter(content_type__app_label="label_printing",
                                                 codename="print_label").exists())
        self.assertTrue(Permission.objects.filter(codename="print_label").exists())
