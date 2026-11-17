"""The print agent's display (panel.py on a PiFace Control & Display) and Bluetooth printers, without the hardware."""
import time

from django.test import SimpleTestCase

from ..agent import Printers
from ..devices import bluetooth, piface
from ..devices.io import RfcommDevice, device_for
from ..panel import ABORT_ALL, BACK, PAUSE_ALL, Panel, scroll
from ..panel import addresses as panel_addresses
from ..devices.piface import LEFT, PRESS, RIGHT


class FakeLink:
    def __init__(self, server="https://inventar.zam.haus"):
        self.server = server
        self.state = {"code": "ok", "message": "", "since": 0.0}
        self.settings, self.waiting, self.loaded = {}, [], []
        self.asked, self.refusal = [], ""

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


class FakeRequest:
    name = "PT-P710BT6522"

    def __init__(self):
        self.answer = None

    def accept(self):
        self.answer = "yes"

    def decline(self):
        self.answer = "no"


ZEBRA = {"uid": "usb-0a5f-00a0-Z1", "device": "/dev/usb/lp0", "language": "zpl", "product": "ZTC GK420t", "dpi": 203}


class PanelTests(SimpleTestCase):
    def setUp(self):
        self.now = 1000.0
        self.printers = Printers([ZEBRA], find=lambda: [])
        self.printers.scan()
        self.link = FakeLink()
        self.link.settings = {ZEBRA["uid"]: {"name": "Zebra Lager", "active": True, "language": "zpl",
                                             "media": [{"id": 1, "name": "57 × 32"}, {"id": 2, "name": "60 × 30"}],
                                             "loaded": 1}}
        self.panel = Panel(None, "pi-lager", clock=lambda: self.now,
                           addresses=lambda: [("wlan0", "192.0.2.23"), ("eth0", "198.51.100.7")])
        self.panel.attach(self.printers, [self.link])

    def texts(self):
        return [(page.title, page.text) for page in self.panel.pages()]

    def go_to(self, title):
        for _ in range(10):
            if self.panel.lines()[0] == title:
                return
            self.panel.press(RIGHT)
        self.fail(f"no page {title}")

    def test_pages(self):
        self.assertEqual(self.texts(), [
            ("pi-lager", "192.0.2.23, Server 1/1, 1 Drucker"),
            ("Netzwerk", "wlan0 192.0.2.23, eth0 198.51.100.7"),
            ("Bluetooth", "aus (config.json)"),
            ("inventar.zam.haus", "✓ verbunden"),
            ("Zebra Lager", "✓ bereit, 57 × 32"),
        ])
        bluetooth = type("Bluetooth", (), {"status": "no_bluez", "problem": "org.bluez was not provided"})()
        self.panel.attach(self.printers, [self.link], bluetooth)
        self.assertEqual(self.texts()[2][1], "✗ kein Zugriff auf BlueZ: org.bluez was not provided")
        self.link.state = {"code": "refused", "message": "unknown token: create the agent", "since": 0.0}
        self.printers.statuses[ZEBRA["uid"]] = {"ok": False, "errors": ["head_open"]}
        self.link.settings = {}
        texts = self.texts()
        self.assertEqual((texts[3][1], texts[4]), ("✗ Token unbekannt (Admin)", ("ZTC GK420t", "✗ Druckkopf offen")))
        self.link.state = {"code": "offline", "message": "refused", "since": self.now - 150}
        self.assertEqual(self.texts()[3][1], "✗ nicht erreichbar seit 2 min")

    def test_labels_waiting_come_first_and_are_confirmed(self):
        self.link.waiting = [{"printer": ZEBRA["uid"], "medium": 2, "material": "60 × 30 (60 × 30 mm labels)",
                              "reason": "Loaded: 57 × 32.", "jobs": 2}]
        self.panel.press(RIGHT)  # somewhere else
        lines = self.panel.lines()  # a new alert: shown at once
        self.assertEqual(lines, ["! Zebra Lager", "60 × 30 (60 × 30"])
        self.assertEqual(self.panel.pages()[0].text,
                         "60 × 30 (60 × 30 mm labels) einlegen: 2 Aufträge warten. Loaded: 57 × 32.")
        self.panel.press(PRESS)
        self.assertEqual(self.panel.lines()[1], "1/2 Ja, ist drin")
        self.panel.press(PRESS)
        for _ in range(50):
            if self.link.loaded:
                break
            time.sleep(0.01)
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 2)])
        self.assertEqual(self.panel.menus, [])

    def test_printer_menu(self):
        self.go_to("Zebra Lager")
        self.panel.press(PRESS)
        self.assertEqual(self.panel.lines(), ["Zebra Lager", "1/5 Anhalten"])
        self.panel.press(PRESS)
        self.assertTrue(self.printers.state(ZEBRA["uid"])["held"])
        self.assertEqual(self.texts()[4][1], "⏸ angehalten (Menü: fortsetzen)")
        self.panel.press(PRESS)
        self.panel.press(RIGHT)  # the labels loaded in the Zebra
        self.panel.press(PRESS)
        self.assertEqual(self.panel.lines()[1], "1/3 ✓ 57 × 32")
        self.panel.press(BACK)
        self.panel.press(LEFT)
        self.panel.press(PRESS)  # go on
        self.assertFalse(self.printers.state(ZEBRA["uid"])["held"])

    def test_test_and_calibration_labels_from_the_menu(self):
        self.panel.background = lambda work: work()
        menu = self.panel.printer_menu(ZEBRA["uid"])
        self.assertEqual([label for label, _action in menu.entries],
                         ["Anhalten", "Etiketten eingelegt", "Testetikett", "Kalibrieretikett", "Zurück"])
        dict(menu.entries)["Kalibrieretikett"]()
        self.assertEqual(self.link.asked, [(ZEBRA["uid"], "calibration")])
        self.assertEqual(self.panel.note, "Kalibrieretikett kommt")
        self.link.refusal = "Er nimmt kein vorrätiges Etikettenmaterial."
        self.panel.print_own_label(self.link, ZEBRA["uid"], "test")
        self.assertEqual(self.panel.note, "✗ Er nimmt kein vorrätiges Etikettenmaterial.")
        self.link.settings[ZEBRA["uid"]]["active"] = False
        self.assertEqual(self.panel.own_label_entries(ZEBRA["uid"]), [])

    def test_a_ribbon_that_does_not_suit_the_labels(self):
        self.link.settings[ZEBRA["uid"]].update(
            ribbons=[{"id": 7, "name": "Wachsband 85 mm, schwarz"}, {"id": 8, "name": "Harzband 110 mm, schwarz"}],
            ribbon=7, ribbon_problem="Das Farbband passt nicht zu den Etiketten: 105 × 52 gelb brauchen ein Harzband, das "
                           "eingelegte ist ein Wachsband 85 mm, schwarz.")
        self.panel.press(RIGHT)  # somewhere else
        self.assertEqual(self.panel.lines()[0], "! Zebra Lager")  # urgent: shown at once, first
        self.assertTrue(self.panel.pages()[0].text.startswith("Farbband passt nicht! Das Farbband"))
        self.assertEqual(self.texts()[5][1], "✗ Farbband passt nicht zu den Etiketten")
        lit = set()
        for _ in range(4):  # the backlight blinks, also long after the last button
            self.now += 1000.35
            lit.add(self.panel.backlight_on())
        self.assertEqual(lit, {True, False})
        self.panel.press(PRESS)
        self.assertEqual(self.panel.lines()[1], "1/4 ✓ Wachsband ")
        self.panel.press(RIGHT)
        self.panel.press(PRESS)
        for _ in range(50):
            if self.link.loaded:
                break
            time.sleep(0.01)
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 8)])
        self.assertFalse(any(page.urgent for page in self.panel.pages()))

    def test_pause_and_abort_all(self):
        self.printers.spooler(ZEBRA["uid"])
        self.panel.press(PAUSE_ALL)
        self.assertTrue(self.printers.state(ZEBRA["uid"])["held"])
        self.panel.press(PAUSE_ALL)
        self.assertFalse(self.printers.state(ZEBRA["uid"])["held"])
        aborted = []
        self.printers.abort = lambda uid=None, by="display": aborted.append(uid)
        self.panel.background = lambda work: work()  # (in a thread of its own on the agent)
        self.panel.press(ABORT_ALL)
        self.assertEqual((aborted, self.panel.lines()[1]), ([], "Alle abbrechen? "))
        self.now += 6
        self.panel.press(ABORT_ALL)  # too late: asks again
        self.panel.press(ABORT_ALL)
        self.assertEqual(aborted, [None])

    def test_pairing_is_asked(self):
        request = FakeRequest()
        self.panel.ask(request)
        self.assertEqual(self.panel.lines(), ["Koppeln? OK/Nein", "PT-P710BT6522"])
        self.panel.press(RIGHT)  # no answer
        self.panel.press(BACK)
        self.assertEqual(request.answer, "no")
        self.panel.ask(request)
        self.panel.press(PRESS)
        self.assertEqual(request.answer, "yes")

    def test_addresses_from_ip(self):
        from unittest.mock import patch

        output = ("3: wlan0    inet 192.0.2.23/24 brd 192.0.2.255 scope global dynamic wlan0\\       valid_lft 1\n"
                  "3: wlan0    inet6 2001:db8::5/64 scope global dynamic\\       valid_lft 1\n"
                  "2: eth0    inet 198.51.100.7/24 scope global eth0\n")
        with patch("label_printing.panel.subprocess.run") as run:
            run.return_value.stdout = output
            self.assertEqual(panel_addresses(), [("wlan0", "192.0.2.23"), ("eth0", "198.51.100.7"),
                                                 ("wlan0", "2001:db8::5")])

    def test_long_texts_scroll(self):
        text = "Etiketten 60 × 30 einlegen"
        self.assertEqual(scroll(text, 0), text[:16])
        self.assertEqual(scroll(text, 6), text[:16])  # stands a moment
        self.assertEqual(scroll(text, 8), text[2:18])
        self.assertEqual(scroll("kurz", 50), "kurz")


class FakeSpi:
    """An MCP23S17: registers written and read over SPI; buttons pressed pull port A bits low."""

    def __init__(self, present=True):
        self.registers, self.present, self.written = {}, present, []

    def xfer2(self, data):
        opcode, register, value = data
        if opcode == piface.WRITE:
            self.registers[register] = value
            self.written.append((register, value))
            return [0, 0, 0]
        if not self.present:
            return [0, 0, 0]
        return [0, 0, self.registers.get(register, 0xFF if register == piface.GPIOA else 0)]


class PiFaceTests(SimpleTestCase):
    def test_display_and_switches(self):
        spi = FakeSpi()
        display = piface.PiFaceCAD(spi)
        self.assertEqual((spi.registers[piface.IODIRA], spi.registers[piface.IODIRB], spi.registers[piface.GPPUA]),
                         (0xFF, 0x00, 0xFF))
        self.assertTrue(spi.registers[piface.GPIOB] & piface.BACKLIGHT)
        self.assertEqual(display.switches(), set())
        spi.registers[piface.GPIOA] = 0xFF & ~0b10100001  # pressed pull low: button 1, navigation pressed, right
        self.assertEqual(display.switches(), {0, piface.PRESS, piface.RIGHT})
        spi.written.clear()
        display.show(["Hä", ""])
        data = [value for register, value in spi.written if register == piface.GPIOB]
        # 4-bit transfers, each nibble with enable high, then low: the DDRAM address, then the characters (RS)
        nibbles = [value & 0x0F for value in data[1::2]]
        self.assertEqual(nibbles[:6], [0x8, 0x0, 0x4, 0x8, 0xE, 0x1])  # 0x80, "H", "ä" (0xE1)
        self.assertTrue(all(value & piface.RS for value in data[4:4 + 16 * 4]))  # the first line's characters
        spi.written.clear()
        display.show(["Hä", ""])
        self.assertEqual(spi.written, [])  # unchanged lines are not written again
        display.backlight(False)
        self.assertFalse(spi.registers[piface.GPIOB] & piface.BACKLIGHT)

    def test_no_board(self):
        with self.assertRaises(piface.NoDisplay):
            piface.PiFaceCAD(FakeSpi(present=False))

    def test_characters(self):
        self.assertEqual(piface.encode("Größe ✓ Ü", 12), [ord("G"), ord("r"), 0xEF, 0xE2, ord("e"), 0x20, 0, 0x20,
                                                           ord("U"), ord("e"), 0x20, 0x20])


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
