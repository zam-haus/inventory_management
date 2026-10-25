import base64
import json
import os
import re
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .. import services
from ..agent import Link, Printers, Refused, servers_of
from ..devices import usb
from ..models import LabelMedium, PrintAgent, Printer
from .helpers import SETTINGS, SimulatedPrinters

BROTHER_INFO = {"language": "ptouch", "model": "P900W", "manufacturer": "Brother", "product": "PT-P900W",
                "serial": "A1B2C3", "usb_id": "04f9:2085", "dpi": 360}


def create_agent(name="pi-lager", active=True):
    agent = PrintAgent(name=name, is_active=active)
    token = agent.new_token()
    agent.last_seen = timezone.now()
    agent.save()
    return agent, token


def usb_zebra(agent, uid="usb-0a5f-00a0-ZEBRA1", slug="zebra-usb"):
    printer = Printer.objects.create(name="Zebra USB", slug=slug, uid=uid, language="zpl", transport="agent",
                                     agent=agent)
    medium = LabelMedium.objects.create(printer=printer, name="57 × 32", width_mm=57, height_mm=32)
    return printer, medium


def temporary_directory(test):
    directory = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, directory)
    return directory


@override_settings(**SETTINGS, PRINT_AGENT_MAX_PRINTERS=3)
class AgentAccessAndPrinterTests(TestCase):
    """Agents are created by an admin and use their token; the printers they report are created inactive."""

    def setUp(self):
        self.agent, self.token = create_agent()

    def post(self, name, data, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token or self.token}"}
        return self.client.post(reverse(name, kwargs=kwargs), json.dumps(data), content_type="application/json",
                                headers=headers)

    def poll(self, printers=None, token=None):
        return self.post("print_agent_poll", {"version": "4", "hostname": "pi-lager", "printers": printers or {}},
                         token=token)

    def test_only_agents_created_in_the_admin_are_let_in(self):
        self.assertEqual(self.client.post("/print/api/agent/register", "{}", content_type="application/json")
                         .status_code, 404)  # nothing registers itself
        response = self.poll(token="wrong" * 10)
        self.assertEqual(response.status_code, 401)
        self.assertIn("create the agent in the admin", response.json()["error"])
        self.assertEqual(self.client.post(reverse("print_agent_poll"), "{}", content_type="application/json")
                         .status_code, 401)
        self.assertEqual(self.poll().json(), {"printers": {}, "job": None})
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.hostname, "pi-lager")
        PrintAgent.objects.filter(pk=self.agent.pk).update(is_active=False)
        response = self.poll({"usb-04f9-2085-A1B2C3": {"info": BROTHER_INFO}})
        self.assertEqual(response.status_code, 403)  # locked out, also from reporting printers
        self.assertFalse(Printer.objects.exists())

    def test_admin_shows_the_token_once_as_configuration_entry(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        response = self.client.post(reverse("admin:label_printing_printagent_add"),
                                    {"name": "pi-werkstatt", "is_active": "on"}, follow=True)
        agent = PrintAgent.objects.get(name="pi-werkstatt")
        token = re.search(r'&quot;token&quot;: &quot;([^&]+)&quot;', response.content.decode()).group(1)
        self.assertContains(response, "&quot;url&quot;: &quot;http://testserver&quot;")
        self.assertEqual(PrintAgent.for_token(token), agent)
        response = self.client.post(reverse("admin:label_printing_printagent_changelist"),
                                    {"action": "new_token", "_selected_action": [agent.pk]}, follow=True)
        self.assertIsNone(PrintAgent.for_token(token))  # the old one stops working
        new = re.search(r'&quot;token&quot;: &quot;([^&]+)&quot;', response.content.decode()).group(1)
        self.assertEqual(PrintAgent.for_token(new), agent)

    def test_new_printers_are_created_inactive(self):
        status = {"language": "ptouch", "ok": True, "errors": [], "media_width_mm": 24, "tape_color": "gelb",
                  "text_color": "schwarz"}
        report = {"usb-04f9-2085-A1B2C3": {"device": "/dev/usb/lp0", "info": BROTHER_INFO, "status": status}}
        self.assertEqual(self.poll(report).json(), {"printers": {}, "job": None})
        printer = Printer.objects.get(uid="usb-04f9-2085-A1B2C3")
        self.assertEqual((printer.name, printer.language, printer.model, printer.dpi, printer.is_active,
                          printer.transport, printer.agent), ("Brother PT-P900W", "ptouch", "P900W", 360, False,
                                                              "agent", self.agent))
        self.assertEqual(printer.slug, "usb-04f9-2085-a1b2c3")
        self.assertEqual(printer.status_text, "Ready. Loaded: 24 mm tape, schwarz on gelb.")
        self.assertEqual(printer.unavailable_code(), "inactive")

    def test_activated_printer_gets_jobs(self):
        self.poll({"usb-04f9-2085-A1B2C3": {"info": BROTHER_INFO}})
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        printer = Printer.objects.get()
        response = self.client.post(reverse("admin:label_printing_printer_changelist"),
                                    {"action": "activate", "_selected_action": [printer.pk]}, follow=True)
        self.assertContains(response, "Brother PT-P900W is active. Add the labels loaded in it.")
        printer.refresh_from_db()
        medium = LabelMedium.objects.create(printer=printer, name="24 mm", ptouch_tape=24)
        job = services.submit(printer=printer, medium=medium, layout_key="test", subject_type="printer",
                              subjects=[printer])
        answer = self.poll().json()
        self.assertEqual(answer["printers"], {"usb-04f9-2085-A1B2C3": {"language": "ptouch", "check_status": True}})
        self.assertEqual((answer["job"]["id"], answer["job"]["printer"], answer["job"]["expected_tape_mm"]),
                         (job.pk, "usb-04f9-2085-A1B2C3", 24))
        self.assertIsNone(answer["job"]["expected_length"])  # Zebra only: [height in mm, dpi]

    def test_unknown_brother_model_must_be_chosen_before_activating(self):
        self.poll({"usb-04f9-20c7-X": {"info": {**BROTHER_INFO, "model": ""}}})
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        response = self.client.post(reverse("admin:label_printing_printer_changelist"),
                                    {"action": "activate", "_selected_action": [Printer.objects.get().pk]}, follow=True)
        self.assertContains(response, "Choose one of E550W")
        self.assertFalse(Printer.objects.get().is_active)

    def test_a_printer_found_again_stays_as_it_was(self):
        printer, _medium = usb_zebra(self.agent)
        Printer.objects.filter(pk=printer.pk).update(is_active=True, name="Zebra Lager")
        self.poll()  # unplugged, or the agent restarted
        self.poll({printer.uid: {"info": {"language": "zpl", "model": "GK420t"}}})
        printer.refresh_from_db()
        self.assertEqual((printer.is_active, printer.name, printer.agent, Printer.objects.count()),
                         (True, "Zebra Lager", self.agent, 1))

    def test_printer_moves_to_another_agent_and_stays_active(self):
        old, _token = create_agent("old")
        printer, _medium = usb_zebra(old)
        Printer.objects.filter(pk=printer.pk).update(is_active=True)
        self.poll({printer.uid: {"info": {"language": "zpl"}}})
        printer.refresh_from_db()
        self.assertEqual((printer.agent, printer.is_active), (self.agent, True))
        inactive, _medium = usb_zebra(old, uid="usb-0a5f-00a0-ZEBRA2", slug="zebra-2")
        Printer.objects.filter(pk=inactive.pk).update(is_active=False)
        self.poll({inactive.uid: {"info": {"language": "zpl"}}})
        inactive.refresh_from_db()
        self.assertEqual((inactive.agent, inactive.is_active), (self.agent, False))

    def test_limits_and_junk(self):
        reports = {f"usb-0a5f-00a0-{n}": {"info": {"language": "zpl"}} for n in range(5)}
        reports["bad id!"] = {"info": {"language": "zpl"}}
        reports["usb-1234-5678-X"] = {"info": {"language": "escp"}}
        self.poll(reports)
        self.assertEqual(Printer.objects.count(), 3)


@override_settings(**SETTINGS)
class AgentApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent, cls.token = create_agent()
        cls.printer, cls.medium = usb_zebra(cls.agent)

    def post(self, name, data=None, token=None, **kwargs):
        return self.client.post(reverse(name, kwargs=kwargs), json.dumps(data or {}), content_type="application/json",
                                headers={"Authorization": f"Bearer {token or self.token}"})

    def queue(self):
        self.printer.refresh_from_db()
        return services.submit(printer=self.printer, medium=self.medium, layout_key="test", subject_type="printer",
                               subjects=[self.printer])

    def test_agent_goes_offline_or_inactive(self):
        PrintAgent.objects.filter(pk=self.agent.pk).update(last_seen=timezone.now() - timedelta(seconds=31))
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.unavailable_reason(), "The print agent of this printer is offline.")
        PrintAgent.objects.filter(pk=self.agent.pk).update(last_seen=timezone.now(), is_active=False)
        self.assertEqual(self.printer.unavailable_code(), "agent_offline")

    def test_job_round_trip(self):
        job = self.queue()
        answer = self.post("print_agent_poll").json()["job"]
        self.assertEqual((answer["printer"], base64.b64decode(answer["payload"])), (self.printer.uid, bytes(job.payload)))
        self.assertIsNone(self.post("print_agent_poll").json()["job"])  # claimed once
        result = {"status": "failed", "code": "head_open", "detail": {}, "printer_status": {"errors": ["head_open"]}}
        self.assertEqual(self.post("print_agent_result", result, pk=job.pk).json(), {"ok": True})
        job.refresh_from_db()
        self.assertEqual((job.status, job.message, job.agent), ("failed", "The print head is open.", self.agent))
        self.assertEqual(self.post("print_agent_result", result, pk=job.pk).status_code, 409)

    def test_only_the_claiming_agent_reports(self):
        job = self.queue()
        self.post("print_agent_poll")
        _other, other_token = create_agent("other")
        self.assertEqual(self.post("print_agent_result", {"status": "done"}, token=other_token, pk=job.pk).status_code, 404)
        self.assertEqual(self.post("print_agent_result", {"status": "maybe"}, pk=job.pk).status_code, 400)


class UsbDiscoveryTests(SimpleTestCase):
    def fake_sysfs(self, devices):
        root = temporary_directory(self)
        for index, (vendor, product, serial) in enumerate(devices):
            usb_dir = os.path.join(root, "devices", f"1-1.{index + 2}")
            interface = os.path.join(usb_dir, f"1-1.{index + 2}:1.0")
            os.makedirs(interface)
            for name, value in (("idVendor", vendor), ("idProduct", product), ("serial", serial),
                                ("manufacturer", "Maker"), ("product", f"Printer {index}")):
                if value is not None:
                    with open(os.path.join(usb_dir, name), "w") as file:
                        file.write(value + "\n")
            os.makedirs(os.path.join(root, "class", f"lp{index}"))
            os.symlink(interface, os.path.join(root, "class", f"lp{index}", "device"))
        return os.path.join(root, "class")

    def test_brother_and_zebra_with_stable_ids(self):
        sysfs = self.fake_sysfs([("04f9", "2085", "A1B2C3"), ("0a5f", "00a0", None), ("03f0", "1234", "HP")])
        found = usb.find_printers(sysfs, "/dev/usb")
        self.assertEqual([(p["uid"], p["device"], p["language"], p["model"]) for p in found], [
            ("usb-04f9-2085-A1B2C3", "/dev/usb/lp0", "ptouch", "P900W"),
            ("usb-0a5f-00a0-1-1.3", "/dev/usb/lp1", "zpl", ""),  # no serial number: the USB port
        ])
        self.assertEqual(found[0]["dpi"], 360)


class AgentConfigurationTests(SimpleTestCase):
    def test_servers_with_their_tokens(self):
        config = {"servers": [{"url": "https://a/", "token": "t1"}]}
        self.assertEqual(servers_of(config, ["http://b:8000", "https://a"], ["t2", "t3"]),
                         [{"url": "https://a", "token": "t3"}, {"url": "http://b:8000", "token": "t2"}])
        for bad in ({"servers": ["https://a"]}, {"servers": [{"url": "https://a"}]}):
            with self.assertRaises(ValueError):
                servers_of(bad)
        with self.assertRaises(ValueError):
            servers_of({"servers": []}, ["https://a"], [])


@override_settings(**SETTINGS)
class AgentTests(SimulatedPrinters, LiveServerTestCase):
    """The agent, created in the admin, works with the live test server and prints on fake printers reached via
    tcp://."""

    def setUp(self):
        super().setUp()
        self.printers = Printers([
            {"uid": "zebra-lan", "device": f"tcp://127.0.0.1:{self.zebra_server.port}", "language": "zpl"},
            {"uid": "ptouch-lan", "device": f"tcp://127.0.0.1:{self.brother_server.port}", "language": "ptouch",
             "model": "E550W"},
        ], find=lambda: [])
        self.agent, token = create_agent("pi-lager")
        self.link = Link({"url": self.live_server_url, "token": token}, self.printers,
                         {"poll_interval": 0, "report_interval": 60}, "pi-test")

    def activate(self, uid):
        Printer.objects.filter(uid=uid).update(is_active=True)
        printer = Printer.objects.get(uid=uid)
        return printer, LabelMedium.objects.create(printer=printer, name="57 × 32", width_mm=57, height_mm=32)

    def test_report_activate_print(self):
        self.brother_state.tape_color = 0x06  # yellow tape
        self.printers.scan()
        self.printers.check()
        self.assertFalse(self.link.poll_once())  # reports both printers
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.hostname, "pi-test")
        zebra = Printer.objects.get(uid="zebra-lan")
        self.assertEqual((zebra.is_active, zebra.dpi, zebra.info["model"]), (False, 203, "GK420t"))
        self.assertEqual(Printer.objects.get(uid="ptouch-lan").last_status["tape_color"], "gelb")

        zebra, medium = self.activate("zebra-lan")
        job = services.submit(printer=zebra, medium=medium, layout_key="test", subject_type="printer",
                              subjects=[zebra], copies=2)
        self.assertTrue(self.link.poll_once())
        job.refresh_from_db()
        self.assertEqual((job.status, job.claimed_by), ("done", "pi-lager"))  # the agent's name in the admin
        self.assertEqual(len(self.zebra_output.printed), 1)

    def test_deactivated_or_deleted_agent_is_refused(self):
        self.link.poll_once()
        PrintAgent.objects.update(is_active=False)
        with self.assertRaisesMessage(Refused, "deactivated in the admin"):
            self.link.poll_once()
        PrintAgent.objects.all().delete()
        with self.assertRaisesMessage(Refused, "unknown token"):
            self.link.poll_once()

    def test_printer_unplugged(self):
        self.printers.scan()
        self.link.poll_once()
        printer, medium = self.activate("zebra-lan")
        job = services.submit(printer=printer, medium=medium, layout_key="test", subject_type="printer",
                              subjects=[printer])
        self.printers.static.clear()
        self.printers.scan()
        self.link.poll_once()
        job.refresh_from_db()
        self.assertEqual((job.status, job.code), ("failed", "unreachable"))
