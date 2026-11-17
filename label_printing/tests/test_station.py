"""What the print agent's display shows and does apart from the screen (station.py), the one server it works for
(agent.Connection), and Bluetooth printers, without the hardware."""
from unittest import mock

from django.test import SimpleTestCase

from ..agent import Connection, Printers
from ..devices import bluetooth
from ..devices.io import RfcommDevice, device_for
from ..station import Station, addresses


class FakeLink:
    def __init__(self, server="https://inventar.zam.haus"):
        self.server = server
        self.state = {"code": "ok", "message": "", "since": 0.0}
        self.settings, self.waiting, self.loaded = {}, [], []
        self.asked, self.refusal = [], ""
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def set_loaded(self, uid, medium):
        self.loaded.append((uid, medium))
        return True

    def set_ribbon(self, uid, ribbon):
        self.loaded.append((uid, ribbon))
        self.settings[uid] = {**self.settings[uid], "ribbon": ribbon, "ribbon_problem": ""}
        return True

    def print_own_label(self, uid, label):
        self.asked.append((uid, label))
        return self.refusal


class FakeConnection:
    """One server, already connected (agent.Connection without its thread)."""

    def __init__(self, link, servers=None):
        self.link, self.index = link, 0
        self.servers = servers or [{"url": link.server, "token": "t"}]
        self.switched = []

    def switch(self, index):
        self.switched.append(index)
        return True


class FakeRequest:
    name = "PT-P710BT6522"

    def __init__(self):
        self.answer = None

    def accept(self):
        self.answer = "yes"

    def decline(self):
        self.answer = "no"


ZEBRA = {"uid": "usb-0a5f-00a0-Z1", "device": "/dev/usb/lp0", "language": "zpl", "product": "ZTC GK420t", "dpi": 203}
SERVERS = [{"url": "https://inventar.zam.haus", "token": "a"}, {"url": "http://192.0.2.10:8000", "token": "b"}]


class ConnectionTests(SimpleTestCase):
    def setUp(self):
        self.printers = Printers([ZEBRA], find=lambda: [])
        self.printers.scan()
        self.connection = Connection(SERVERS, self.printers, {}, "pi", link=lambda server, *args: FakeLink(server["url"]))
        self.connection.start()

    def test_the_first_server_and_another_one_chosen(self):
        first = self.connection.link
        self.assertEqual((first.server, first.started), ("https://inventar.zam.haus", True))
        self.assertTrue(self.connection.switch(1))
        self.assertTrue(first.stopped)  # asks no more, takes no more jobs
        self.assertEqual((self.connection.index, self.connection.link.server, self.connection.link.started),
                         (1, "http://192.0.2.10:8000", True))
        self.assertTrue(self.connection.switch(1))  # already: nothing changes
        self.assertFalse(self.connection.switch(5))

    def test_not_while_a_printer_has_jobs(self):
        self.printers.spooler(ZEBRA["uid"]).pause()  # held: the old server's matter
        self.assertFalse(self.connection.switch(1))
        self.assertEqual(self.connection.index, 0)

    def test_the_display_switches_and_says_so(self):
        station = Station("pi", clock=lambda: 0.0, addresses=lambda: [])
        station.attach(self.printers, self.connection)
        station.switch_server(1)
        self.assertEqual((station.link.server, station.note), ("http://192.0.2.10:8000", "verbinde mit 192.0.2.10 ..."))
        self.printers.spooler(ZEBRA["uid"]).pause()
        station.switch_server(0)
        self.assertEqual((station.connection.index, station.note), (1, "✗ erst die Aufträge abwarten oder abbrechen"))


class AddressTests(SimpleTestCase):
    def test_addresses_from_ip(self):
        output = ("3: wlan0    inet 192.0.2.23/24 brd 192.0.2.255 scope global dynamic wlan0\\       valid_lft 1\n"
                  "3: wlan0    inet6 2001:db8::5/64 scope global dynamic\\       valid_lft 1\n"
                  "2: eth0    inet 198.51.100.7/24 scope global eth0\n")
        with mock.patch("label_printing.station.subprocess.run") as run:
            run.return_value.stdout = output
            self.assertEqual(addresses(), [("wlan0", "192.0.2.23"), ("eth0", "198.51.100.7"), ("wlan0", "2001:db8::5")])


class BluetoothTests(SimpleTestCase):
    def test_printers_by_name_and_class(self):
        self.assertEqual(bluetooth.model_of("PT-P710BT6522"), "P710BT")
        self.assertEqual(bluetooth.model_of("PT-P910BT0001"), "P910BT")
        self.assertEqual(bluetooth.model_of("Pixel 8"), "")
        self.assertTrue(bluetooth.is_printer({"Name": "PT-P710BT6522"}))
        self.assertTrue(bluetooth.is_printer({"Name": "PT-X99", "Class": 0x040680}))  # imaging, printer
        self.assertFalse(bluetooth.is_printer({"Name": "Kopfhörer", "Class": 0x240404}))
        entry = bluetooth.printer_entry({"Address": "a1:b2:c3:d4:e5:f6", "Name": "PT-P710BT6522"})
        self.assertEqual(entry, {"uid": "bt-a1b2c3d4e5f6", "device": "bt://A1:B2:C3:D4:E5:F6/1", "language": "ptouch",
                                 "model": "P710BT", "manufacturer": "Brother", "product": "PT-P710BT6522",
                                 "bluetooth": "A1:B2:C3:D4:E5:F6", "dpi": 180})

    def test_bluetooth_addresses(self):
        device = device_for("bt://a1:b2:c3:d4:e5:f6/2")
        self.assertIsInstance(device, RfcommDevice)
        self.assertEqual(str(device), "bt://A1:B2:C3:D4:E5:F6/2")
        self.assertEqual(device_for("bt://A1:B2:C3:D4:E5:F6").channel, 1)
        with self.assertRaises(ValueError):
            device_for("bt://printer")
