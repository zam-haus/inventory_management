"""Print agents of version 5: printers print at the same time, jobs can be paused and aborted (on the agent's display
or in the admin), and agents learn which labels wait for one of their printers to be loaded with them."""
import json
import threading
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .. import drivers, outcomes, services, simulator
from ..agent import Link, Printers, Task
from ..api import job_data
from ..devices import brother, zebra
from ..devices.io import TcpDevice
from ..devices.run import Control, run_job
from ..models import LabelStock, Medium, Printer, PrintJob, Ribbon, ribbon_problem
from .helpers import SETTINGS, SimulatedPrinters, labels, outcome_key
from .test_agent import create_agent, usb_zebra
from .test_dialog import InventoryData


@override_settings(**SETTINGS)
class PollTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.agent, cls.token = create_agent()
        cls.zebra, cls.labels = usb_zebra(cls.agent)
        cls.zebra.is_active, cls.zebra.loaded_medium = True, cls.labels.stock
        cls.zebra.save()
        cls.brother = Printer.objects.create(name="P-touch USB", slug="ptouch-usb", uid="usb-04f9-2060-B1",
                                             language="ptouch", model="E550W", dpi=180, transport="agent",
                                             agent=cls.agent)
        cls.tape = labels(cls.brother, name="12 mm", ptouch_tape=12)

    def post(self, name, data, token=None, **kwargs):
        return self.client.post(reverse(name, kwargs=kwargs), json.dumps(data), content_type="application/json",
                                headers={"Authorization": f"Bearer {token or self.token}"})

    def poll(self, busy=(), printing=None, held=None):
        return self.post("print_agent_poll", {"version": "6.0", "hostname": "pi", "printers": {}, "busy": list(busy),
                                              "printing": printing or {},
                                              **({"held": list(held)} if held is not None else {})}).json()

    def queue(self, printer, medium):
        return services.submit(printer=printer, medium=medium, layout_key="test", subject_type="printer",
                               subjects=[printer])

    def test_a_job_for_each_free_printer(self):
        first, second = self.queue(self.zebra, self.labels), self.queue(self.zebra, self.labels)
        on_tape = self.queue(self.brother, self.tape)
        answer = self.poll()
        self.assertEqual(sorted(job["id"] for job in answer["jobs"]), [first.pk, on_tape.pk])
        self.assertEqual(self.poll(busy=[self.zebra.uid])["jobs"], [])  # still printing the first
        self.assertEqual([job["id"] for job in self.poll()["jobs"]], [second.pk])
        ribbons = answer["printers"][self.zebra.uid].pop("ribbons")
        media = answer["printers"][self.zebra.uid].pop("media")  # Zebra labels on hand (also those of migration 0002)
        self.assertIn({"id": self.labels.pk, "name": "57 × 32"}, media)
        self.assertEqual([ribbon["name"] for ribbon in ribbons], [
            "wax ribbon 110 mm, schwarz", "wax/resin ribbon 110 mm, schwarz", "resin ribbon 110 mm, schwarz",
            "wax ribbon 110 mm, rot", "wax/resin ribbon 110 mm, rot", "resin ribbon 110 mm, rot"])  # migration 0005
        self.assertEqual(answer["printers"][self.zebra.uid], {
            "name": "Zebra USB", "active": True, "language": "zpl", "check_status": True,
            "loaded": self.labels.pk,
            "ribbon": None, "ribbon_problem": ""})
        self.assertNotIn("media", answer["printers"][self.brother.uid])  # a Brother reports its tape itself

    def test_a_long_queue_of_one_printer_does_not_hide_the_others_jobs(self):
        backlog = [self.queue(self.zebra, self.labels) for _number in range(60)]
        on_tape = self.queue(self.brother, self.tape)
        self.assertEqual(sorted(job["id"] for job in self.poll()["jobs"]), [backlog[0].pk, on_tape.pk])

    def test_a_held_printer_goes_on_from_the_admin(self):
        self.assertEqual(self.poll(busy=[self.zebra.uid], held=[self.zebra.uid])["printer_commands"], {})
        self.zebra.refresh_from_db()
        self.assertIsNotNone(self.zebra.held_at)
        with self.assertRaisesMessage(services.PrintError, "P-touch USB is not held."):
            services.resume_printer(self.brother)
        services.resume_printer(self.zebra)
        self.assertEqual(self.poll(busy=[self.zebra.uid], held=[self.zebra.uid])["printer_commands"],
                         {self.zebra.uid: "resume"})
        self.poll()  # an agent before 5.1 (no "held") changes nothing
        self.assertEqual(self.poll(held=[])["printer_commands"], {})
        self.zebra.refresh_from_db()
        self.assertEqual((self.zebra.held_at, self.zebra.resume_requested), (None, False))

    def test_jobs_held_by_the_agent_keep_their_lease(self):
        job = self.queue(self.zebra, self.labels)
        self.poll()
        PrintJob.objects.filter(pk=job.pk).update(claimed_at=timezone.now() - timedelta(seconds=170))
        self.poll(busy=[self.zebra.uid], printing={str(job.pk): {"printer": self.zebra.uid, "paused": True}})
        job.refresh_from_db()
        self.assertGreater(job.claimed_at, timezone.now() - timedelta(seconds=5))
        self.assertEqual((job.status, job.message), ("processing", "Paused on the print agent."))
        self.poll(busy=[self.zebra.uid], printing={str(job.pk): {"printer": self.zebra.uid, "paused": False}})
        job.refresh_from_db()
        self.assertEqual((job.paused_at, job.message), (None, "printing"))

    def test_commands_from_the_admin_until_carried_out(self):
        job = self.queue(self.zebra, self.labels)
        self.poll()
        printing = {str(job.pk): {"printer": self.zebra.uid, "paused": False}}
        self.assertIn("gets the command “pause”", services.control(job, "pause"))
        self.assertEqual(self.poll([self.zebra.uid], printing)["commands"], {str(job.pk): "pause"})
        self.assertEqual(self.poll([self.zebra.uid], printing)["commands"], {str(job.pk): "pause"})  # not yet
        printing[str(job.pk)]["paused"] = True
        self.assertEqual(self.poll([self.zebra.uid], printing)["commands"], {})
        services.control(job, "resume")
        self.assertEqual(self.poll([self.zebra.uid], printing)["commands"], {str(job.pk): "resume"})
        services.control(job, "abort")
        self.assertEqual(self.poll([self.zebra.uid], printing)["commands"], {str(job.pk): "abort"})
        self.post("print_agent_result", {"status": "failed", "code": "aborted", "detail": {"by": "server"}}, pk=job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.message), ("failed", "The print was aborted."))
        self.assertEqual(self.poll()["commands"], {})
        with self.assertRaisesMessage(services.PrintError, "is failed"):
            services.control(job, "pause")

    def test_jobs_not_printed_yet_are_aborted_at_once(self):
        job = self.queue(self.zebra, self.labels)
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        response = self.client.post(reverse("admin:label_printing_printjob_changelist"),
                                    {"action": "abort", "_selected_action": [job.pk]}, follow=True)
        self.assertContains(response, f"Job {job.pk} aborted before it was printed.")
        job.refresh_from_db()
        self.assertEqual((job.status, job.code, job.payload), ("failed", "aborted", None))
        self.assertEqual(self.poll()["jobs"], [])
        network = Printer.objects.create(name="Netz", slug="netz", language="zpl", host="192.0.2.1")
        job = PrintJob.objects.create(printer=network, layout_key="test", subject_type="printer",
                                      status=PrintJob.Status.PROCESSING)
        with self.assertRaisesMessage(services.PrintError, "cannot be stopped"):
            services.control(job, "abort")

    def test_labels_waiting_for_a_printer_with_other_labels(self):
        """The agent's display says which labels to put into which printer; on a Zebra, it sets them as loaded."""
        small = labels(self.zebra, name="60 × 30", width_mm=60, height_mm=30)
        found = {outcome.key: outcome for outcome in outcomes.outcomes("location")}
        job = services.submit_outcome(found[outcome_key("location", "60x30")], subject_type="location",
                                      subjects=[self.part], wait=True)
        services.submit_outcome(found[outcome_key("location", "60x30")], subject_type="location",
                                subjects=[self.part], wait=True)
        answer = self.poll()
        self.assertEqual(answer["waiting"], [{"printer": self.zebra.uid, "medium": small.pk,
                                              "material": "60 × 30 (60 × 30 mm labels)",
                                              "reason": "Loaded: 57 × 32.", "jobs": 2, "ribbon_problem": ""}])
        other, other_token = create_agent("other")
        self.assertEqual(self.post("print_agent_poll", {"version": "6.0", "busy": []}, token=other_token)
                         .json()["waiting"], [])
        self.assertEqual(self.post("print_agent_loaded", {"printer": self.zebra.uid, "medium": small.pk},
                                   token=other_token).status_code, 404)
        self.assertEqual(self.post("print_agent_loaded", {"printer": self.zebra.uid, "medium": self.tape.pk})
                         .status_code, 400)
        self.assertEqual(self.post("print_agent_loaded", {"printer": self.zebra.uid, "medium": small.pk}).json(),
                         {"ok": True})
        job.refresh_from_db()
        self.assertEqual((job.status, job.printer), ("waiting", None))  # until the Zebra takes it
        answer = self.poll()
        self.assertEqual(([entry["id"] for entry in answer["jobs"]], answer["waiting"]), ([job.pk], []))
        self.assertEqual(answer["printers"][self.zebra.uid]["loaded"], small.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.printer, job.medium), ("processing", self.zebra, small.stock))

    def test_test_and_calibration_labels_asked_for_on_the_display(self):
        response = self.post("print_agent_own_label", {"printer": self.zebra.uid, "label": "calibration"})
        job = PrintJob.objects.get(pk=response.json()["job"])
        self.assertEqual((job.printer, job.medium, job.layout_key, job.status),
                         (self.zebra, self.labels.stock, "calibration", "waiting"))
        self.assertEqual([entry["id"] for entry in self.poll()["jobs"]], [job.pk])
        self.assertEqual(self.post("print_agent_own_label", {"printer": self.zebra.uid, "label": "x"}).json(),
                         {"error": "Unknown layout."})
        other, other_token = create_agent("other")
        self.assertEqual(self.post("print_agent_own_label", {"printer": self.zebra.uid, "label": "test"},
                                   token=other_token).status_code, 404)
        LabelStock.objects.filter(language="ptouch").update(in_stock=False)  # and no tape reported
        response = self.post("print_agent_own_label", {"printer": self.brother.uid, "label": "test"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("It takes no label material on hand.", response.json()["error"])


@override_settings(**SETTINGS)
class RibbonTests(TestCase):
    """Ribbons are changed in a Zebra like its labels; whether one suits the labels is told by material."""

    @classmethod
    def setUpTestData(cls):
        cls.agent, cls.token = create_agent()
        cls.zebra, cls.labels = usb_zebra(cls.agent)
        cls.paper = LabelStock.objects.create(language="zpl", name="70x32 Papier", width_mm=70, height_mm=32,
                                              method="transfer", ribbon="wax", material="Papier")
        cls.polyester = LabelStock.objects.create(language="zpl", name="105x52 Polyester", width_mm=105,
                                                  height_mm=52, method="transfer", ribbon="resin",
                                                  background_color="gelb")
        cls.wax = Ribbon.objects.create(material="wax", width_mm=84)
        cls.resin = Ribbon.objects.create(material="resin", width_mm=111)
        cls.polyester.name = "105 × 52 gelb"
        cls.polyester.save()
        Printer.objects.filter(pk=cls.zebra.pk).update(is_active=True, loaded_medium=cls.polyester, loaded_ribbon=cls.wax)

    def on_polyester(self):
        return Medium(Printer.objects.select_related("loaded_ribbon").get(pk=self.zebra.pk), self.polyester)

    def post(self, name, data):
        return self.client.post(reverse(name), json.dumps(data), content_type="application/json",
                                headers={"Authorization": f"Bearer {self.token}"})

    def test_kinds_that_suit(self):
        kinds = {"wax": Ribbon(material="wax", width_mm=80), "wax_resin": Ribbon(material="wax_resin", width_mm=80),
                 "resin": Ribbon(material="resin", width_mm=80)}
        media = {needed: LabelStock.objects.create(
            language="zpl", name=needed, width_mm=50, height_mm=30, method="transfer", ribbon=needed)
            for needed in kinds}
        fits = {(needed, kind) for needed in kinds for kind, ribbon in kinds.items()
                if not ribbon_problem(media[needed], ribbon)}
        self.assertEqual(fits, {("wax", "wax"), ("wax", "wax_resin"), ("wax_resin", "wax_resin"),
                                ("wax_resin", "resin"), ("resin", "resin")})
        direct = LabelStock.objects.create(language="zpl", name="direkt", width_mm=50, height_mm=30, method="direct")
        self.assertEqual(ribbon_problem(direct, kinds["wax"]), "")
        self.assertEqual(ribbon_problem(LabelStock(name="ohne Verfahren"), kinds["wax"]), "")  # not known: no warning
        self.assertEqual(ribbon_problem(self.polyester, None), "")
        self.assertEqual(ribbon_problem(self.polyester, self.wax), "The ribbon does not suit the labels: "
                         "105 × 52 gelb need a resin ribbon, the loaded one is a wax ribbon 84 mm, schwarz.")

    def test_a_zebra_prints_in_the_colour_of_its_ribbon(self):
        from inventory.models import LocationLabelTemplate
        from ..layouts.designs import stock_matches

        medium = self.on_polyester()
        self.assertEqual(medium.colours(), ("schwarz", "gelb"))
        red = Ribbon.objects.create(material="resin", width_mm=111, color="rot")
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_ribbon=red)
        medium = self.on_polyester()
        self.assertEqual(medium.colours(), ("rot", "gelb"))
        red_on_yellow = LocationLabelTemplate(name="Warnung", print_color="rot", background_color="gelb")
        black_on_yellow = LocationLabelTemplate(name="Schild", print_color="schwarz", background_color="gelb")
        self.assertEqual((stock_matches(red_on_yellow, medium), stock_matches(black_on_yellow, medium)), (True, False))
        direct = LabelStock.objects.create(language="zpl", name="Thermo", width_mm=50, height_mm=30, method="direct",
                                           background_color="weiß")
        self.assertEqual(labels(medium.printer, save=False, stock=direct, name="T").colours(), ("", "weiß"))
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_ribbon=None)
        self.assertEqual(self.on_polyester().colours(), ("", "gelb"))  # print: not known

    def test_the_agent_hears_of_it_and_sets_another(self):
        answer = self.post("print_agent_poll", {"version": "6.0", "busy": []}).json()["printers"][self.zebra.uid]
        ours = [ribbon for ribbon in answer["ribbons"] if ribbon["id"] in (self.wax.pk, self.resin.pk)]
        self.assertEqual((ours, answer["ribbon"]), (
            [{"id": self.wax.pk, "name": "wax ribbon 84 mm, schwarz"},
             {"id": self.resin.pk, "name": "resin ribbon 111 mm, schwarz"}], self.wax.pk))
        self.assertIn("need a resin ribbon", answer["ribbon_problem"])
        self.assertEqual(self.post("print_agent_ribbon", {"printer": self.zebra.uid, "ribbon": 999}).status_code, 400)
        self.assertEqual(self.post("print_agent_ribbon", {"printer": "other", "ribbon": None}).status_code, 404)
        self.assertEqual(self.post("print_agent_ribbon", {"printer": self.zebra.uid, "ribbon": self.resin.pk}).json(),
                         {"ok": True, "ribbon_problem": ""})
        self.assertEqual(Printer.objects.get(pk=self.zebra.pk).loaded_ribbon, self.resin)
        self.post("print_agent_ribbon", {"printer": self.zebra.uid, "ribbon": None})
        self.assertIsNone(Printer.objects.get(pk=self.zebra.pk).loaded_ribbon)

    def test_admin_warns(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        response = self.client.get(reverse("admin:label_printing_printer_changelist"))
        self.assertContains(response, "<strong>⚠ The ribbon does not suit the labels")
        self.assertContains(self.client.get(reverse("admin:label_printing_ribbon_changelist")), "Zebra USB")


@override_settings(**SETTINGS)
class AgentControlTests(SimulatedPrinters, LiveServerTestCase):
    """The agent with the live test server and fake printers: printing in parallel, pausing and aborting."""

    def setUp(self):
        super().setUp()
        self.printers = Printers([
            {"uid": "zebra-lan", "device": f"tcp://127.0.0.1:{self.zebra_server.port}", "language": "zpl",
             "dpi": 203},
            {"uid": "ptouch-lan", "device": f"tcp://127.0.0.1:{self.brother_server.port}", "language": "ptouch",
             "model": "E550W", "dpi": 180},
        ], find=lambda: [])
        self.agent, token = create_agent("pi-lager")
        self.link = Link({"url": self.live_server_url, "token": token}, self.printers,
                         {"poll_interval": 0, "report_interval": 60}, "pi-test")
        self.printers.scan()
        self.link.poll_once()  # reports both printers
        self.zebra = Printer.objects.get(uid="zebra-lan")
        self.labels = labels(self.zebra, name="57 × 32", width_mm=57, height_mm=32)
        self.brother = Printer.objects.get(uid="ptouch-lan")
        self.tape = labels(self.brother, name="12 mm", ptouch_tape=12)
        Printer.objects.filter(pk__in=[self.zebra.pk, self.brother.pk]).update(is_active=True)
        Printer.objects.filter(pk=self.zebra.pk).update(loaded_medium=self.labels.stock)

    def queue(self, printer, medium):
        printer.refresh_from_db()
        return services.submit(printer=printer, medium=medium, layout_key="test", subject_type="printer",
                               subjects=[printer])

    def held_task(self, job, uid="zebra-lan"):
        """The job taken by the agent's printer and waiting in it, held."""
        self.assertEqual(services.take(Printer.objects.get(uid=uid), self.agent.name, self.agent), job)
        job.refresh_from_db()
        self.printers.spooler(uid).pause()
        self.printers.submit(Task(self.link, job_data(job)))

    def test_printers_print_at_the_same_time(self):
        jobs = [self.queue(self.zebra, self.labels), self.queue(self.brother, self.tape)]
        self.assertTrue(self.link.poll_once())  # both in one poll
        self.printers.wait_idle()
        self.assertEqual([PrintJob.objects.get(pk=job.pk).status for job in jobs], ["done", "done"])
        self.assertEqual((len(self.zebra_output.printed), len(self.brother_output.printed)), (1, 1))

    def test_a_held_printer_gets_no_jobs(self):
        job = self.queue(self.zebra, self.labels)
        self.printers.spooler("zebra-lan").pause()  # on the display
        self.assertFalse(self.link.poll_once())
        self.assertEqual(PrintJob.objects.get(pk=job.pk).status, "waiting")
        self.printers.resume("zebra-lan")
        self.assertTrue(self.link.poll_once())
        self.printers.wait_idle()
        self.assertEqual(PrintJob.objects.get(pk=job.pk).status, "done")

    def test_pausing_all_holds_also_printers_that_have_not_printed_yet(self):
        job = self.queue(self.zebra, self.labels)
        self.printers.pause()  # button 4 on the display, before either printer printed
        self.assertEqual(self.printers.busy(), ["ptouch-lan", "zebra-lan"])
        self.assertFalse(self.link.poll_once())
        self.assertEqual(PrintJob.objects.get(pk=job.pk).status, "waiting")

    def test_abort_on_the_display(self):
        job = self.queue(self.zebra, self.labels)
        self.held_task(job)
        self.link.poll_once()
        job.refresh_from_db()
        self.assertEqual(job.message, "Paused on the print agent.")
        self.printers.abort("zebra-lan")
        job.refresh_from_db()
        self.assertEqual((job.status, job.code, job.detail), ("failed", "aborted", {"by": "display"}))
        self.assertEqual(self.zebra_output.printed, [])

    def test_commands_from_the_admin(self):
        job = self.queue(self.zebra, self.labels)
        self.held_task(job)
        services.control(job, "resume")
        self.link.poll_once()
        self.printers.wait_idle()
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        job = self.queue(self.zebra, self.labels)
        self.held_task(job)
        self.link.poll_once()
        services.control(job, "abort")
        self.link.poll_once()
        job.refresh_from_db()
        self.assertEqual((job.status, job.code, job.detail), ("failed", "aborted", {"by": "server"}))

    def test_a_printer_held_by_a_job_aborted_since_goes_on_from_the_admin(self):
        job = self.queue(self.zebra, self.labels)
        self.held_task(job)  # as if paused from the admin
        self.link.poll_once()
        services.control(job, "abort")
        self.link.poll_once()
        self.zebra.refresh_from_db()
        self.assertIsNotNone(self.zebra.held_at)  # held still, without any job
        later = self.queue(self.zebra, self.labels)
        services.resume_printer(self.zebra)
        self.link.poll_once()  # goes on
        self.assertTrue(self.link.poll_once())  # and gets the next job
        self.printers.wait_idle()
        self.assertEqual(PrintJob.objects.get(pk=later.pk).status, "done")
        self.link.poll_once()
        self.zebra.refresh_from_db()
        self.assertEqual((self.zebra.held_at, self.zebra.resume_requested), (None, False))

    def test_the_display_sets_the_labels_loaded_in_a_zebra(self):
        small = labels(self.zebra, name="60 × 30", width_mm=60, height_mm=30)
        self.link.poll_once()
        self.assertIn({"id": small.pk, "name": "60 × 30"}, self.link.settings["zebra-lan"]["media"])
        self.assertTrue(self.link.set_loaded("zebra-lan", small.pk))
        self.assertEqual(Printer.objects.get(pk=self.zebra.pk).loaded_medium, small.stock)
        self.assertFalse(self.link.set_loaded("zebra-lan", self.tape.pk))
        ribbon = Ribbon.objects.create(material="resin", width_mm=60)
        self.assertTrue(self.link.set_ribbon("zebra-lan", ribbon.pk))
        self.assertEqual((Printer.objects.get(pk=self.zebra.pk).loaded_ribbon, self.link.settings["zebra-lan"]["ribbon"]),
                         (ribbon, ribbon.pk))

    def test_the_display_asks_for_a_test_label(self):
        self.assertEqual(self.link.print_own_label("ptouch-lan", "test"), "")
        self.assertTrue(self.link.poll_once())
        self.printers.wait_idle()
        self.assertEqual(PrintJob.objects.get().status, "done")
        self.assertEqual(len(self.brother_output.printed), 1)
        Printer.objects.filter(pk=self.brother.pk).update(is_active=False)
        self.assertNotEqual(self.link.print_own_label("ptouch-lan", "test"), "")  # switched off in the admin


@override_settings(**SETTINGS)
class PauseAndAbortTests(SimulatedPrinters, SimpleTestCase):
    """run_job with a control: the data goes out label by label, a paused job waits, an aborted one stops."""

    def run_in_thread(self, *args, **kwargs):
        results = []
        thread = threading.Thread(target=lambda: results.append(run_job(*args, **kwargs)))
        thread.start()
        return thread, results

    def zebra(self):
        return TcpDevice("127.0.0.1", self.zebra_server.port)

    def test_zebra_pauses_and_goes_on(self):
        control = Control()
        control.pause()
        thread, results = self.run_in_thread(self.zebra(), "zpl", b"^XA^FDa^FS^XZ^XA^FDb^FS^XZ", pages=2,
                                             timeout=5, control=control)
        time.sleep(0.5)
        self.assertEqual(self.zebra_output.printed, [])  # longer than the timeout would be, nothing sent
        control.resume()
        thread.join(10)
        self.assertEqual(results[0].status, "done")
        self.assertEqual(len(self.zebra_output.printed), 2)

    def test_zebra_aborted(self):
        control = Control()
        control.pause()
        thread, results = self.run_in_thread(self.zebra(), "zpl", b"^XA^FDa^FS^XZ", timeout=5, control=control)
        time.sleep(0.2)
        control.abort("display")
        thread.join(10)
        self.assertEqual((results[0].status, results[0].code, results[0].detail), ("failed", "aborted",
                                                                                   {"by": "display"}))
        self.assertEqual(self.zebra_output.printed, [])

    def test_zebra_pause_command_holds_the_printer(self):
        printer = simulator.ZebraPrinter(simulator.PrinterState(), simulator.Output(), render=None)
        self.addCleanup(printer.stopped.set)
        printer.control("~PP")
        self.assertEqual(zebra.parse(printer.status())["errors"], ["paused"])
        printer.add("^XA^XZ")
        printer.control("~JA")
        printer.control("~PS")
        self.assertEqual(zebra.parse(printer.status())["formats_in_buffer"], 0)

    def test_brother_aborted_before_the_next_label(self):
        from PIL import Image

        pins = drivers.ptouch_print_pins("E550W", 12)
        payload, pages = drivers.ptouch_job("E550W", 12, [Image.new("1", (40, pins), 1)] * 3)
        control = Control()
        control.pause()
        thread, results = self.run_in_thread(TcpDevice("127.0.0.1", self.brother_server.port), "ptouch", payload,
                                             pages=pages, expected_tape_mm=12, timeout=5, control=control)
        time.sleep(0.2)
        control.abort("server")
        thread.join(10)
        self.assertEqual((results[0].status, results[0].code), ("failed", "aborted"))
        self.assertEqual(self.brother_output.printed, [])

    def test_jobs_split_into_labels(self):
        from PIL import Image

        pins = drivers.ptouch_print_pins("E550W", 12)
        payload, _pages = drivers.ptouch_job("E550W", 12, [Image.new("1", (40, pins), 0)] * 3)
        parts = brother.split_pages(payload)
        self.assertEqual((len(parts), b"".join(parts)), (3, payload))
        self.assertEqual([part[-1] for part in parts], [0x0C, 0x0C, 0x1A])
        self.assertEqual(brother.split_pages(b"x"), [b"x"])  # not raster data: in one piece
        self.assertEqual(zebra.split_pages(b"^XA^FDa^XZ\n^XA^FDb^XZ"), [b"^XA^FDa^XZ", b"\n^XA^FDb^XZ"])
        self.assertEqual(zebra.split_pages(b"~HS"), [b"~HS"])
