"""The print agent's touch screen (touch.py), without screen and pygame: what it lays out and what taps do."""
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from .. import agent
from ..agent import Printers, Task
from ..devices import bluetooth
from ..touch import CONTENT_TOP, Touch
from .test_panel import ZEBRA, FakeLink, FakeRequest


def measure(text, size, bold=False):
    return len(text) * size * 0.55


class FakeBluetooth:
    status, problem, searching = "ready", "", False

    def __init__(self):
        self.entries = [{"address": "A1:B2:C3:D4:E5:F6", "name": "PT-P710BT6522", "state": "paired"},
                        {"address": "11:22:33:44:55:66", "name": "PT-P910BT0815", "state": "new"}]
        self.calls = []

    def found(self):
        return self.entries

    def search(self):
        self.calls.append("search")

    def pair(self, address):
        self.calls.append(("pair", address))

    def unpair(self, address):
        self.calls.append(("unpair", address))


class TouchTests(SimpleTestCase):
    def setUp(self):
        self.now = 1000.0
        self.printers = Printers([ZEBRA], find=lambda: [])
        self.printers.scan()
        self.link = FakeLink()
        self.link.settings = {ZEBRA["uid"]: {
            "name": "Zebra Lager", "active": True, "language": "zpl", "loaded": 1,
            "media": [{"id": 1, "name": "57 × 32"}, {"id": 2, "name": "60 × 30"}],
            "ribbons": [{"id": 5, "name": "Wachsband 110 mm, schwarz"}], "ribbon": None}}
        self.bluetooth = FakeBluetooth()
        self.touch = Touch(None, "pi-lager", backlight_timeout=600, version="5.2", clock=lambda: self.now,
                           addresses=lambda: [("wlan0", "192.0.2.23")], measure=measure)
        self.touch.attach(self.printers, [self.link], self.bluetooth)
        self.touch.background = lambda work: work()  # (a thread of its own on the agent)

    def items(self, kind=None):
        frame = self.touch.update()
        found = frame.overlay + frame.choices if self.touch.dialogs else frame.fixed + frame.content
        return [item for item in found if kind is None or item.kind == kind]

    def texts(self):
        return [item.text for item in self.items("text")]

    def labels(self):
        return [item.label for item in self.items("button") if item.action is not None]

    def press(self, label):
        """Tap the middle of the button with this label, as a finger on the screen would."""
        frame = self.touch.update()
        layers = [(frame.overlay, 0, 0)] if self.touch.dialogs else [
            (frame.fixed, 0, 0), (frame.content, 0, CONTENT_TOP - self.touch.scroll.get(self.touch.view_key(), 0))]
        if frame.choices_area is not None:
            left, top, _, height = frame.choices_area
            layers.append((frame.choices, left, top - frame.choices_scroll))
        for items, dx, dy in layers:
            for item in items:
                if item.kind == "button" and item.label == label:
                    x, y = item.x + dx + item.w // 2, item.y + dy + item.h // 2
                    if items is frame.choices:
                        self.assertTrue(top <= y < top + height, f"{label!r} is scrolled out of sight")
                    self.assertTrue(self.touch.tap(x, y), label)
                    return
        self.fail(f"no button {label!r} in {self.labels()}")

    def queue_job(self, job_id=7, pages=3):
        self.printers.spooler(ZEBRA["uid"]).pause()  # held: the job waits, nothing is sent
        self.printers.submit(Task(self.link, {"id": job_id, "printer": ZEBRA["uid"], "pages": pages,
                                              "subject": "R303.a Regal 303 Fach a"}))

    def test_tabs(self):
        self.assertIn("Keine Aufträge", self.texts())
        self.press("Drucker")
        self.assertIn("Zebra Lager", self.texts())
        self.assertIn("USB · ✓ bereit, 57 × 32", self.texts())
        self.press("Verbindung")
        self.assertIn("✓ verbunden", self.texts())
        self.assertIn("192.0.2.23", self.texts())
        self.assertIn("5.2", self.texts())
        self.press("Bluetooth")
        self.assertIn("A1:B2:C3:D4:E5:F6 · gekoppelt", self.texts())

    def test_labels_waiting_come_first_and_are_confirmed(self):
        self.link.waiting = [{"printer": ZEBRA["uid"], "medium": 2, "material": "60 × 30", "jobs": 2}]
        self.assertIn("Aufträge (1!)", self.labels())
        self.assertIn("! Zebra Lager", self.texts())
        self.press("Sind eingelegt")
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 2)])

    def test_jobs_of_a_printer_paused_and_aborted(self):
        self.queue_job()
        texts = self.texts()
        self.assertIn("· #7 R303.a Regal 303 Fach a · 3 Etiketten", texts)
        self.assertIn("⏸ angehalten", texts)
        self.press("Fortsetzen")
        self.assertFalse(self.printers.state(ZEBRA["uid"])["held"])
        self.printers.spooler(ZEBRA["uid"]).pause()
        aborted = []
        self.printers.abort = lambda uid=None, by="display": aborted.append(uid)
        self.press("Abbrechen")
        self.assertIn("Zebra Lager: alle Aufträge abbrechen?", self.texts())
        self.press("Nein")
        self.assertEqual(aborted, [])
        self.press("Abbrechen")
        self.press("Ja, abbrechen")
        self.assertEqual(aborted, [ZEBRA["uid"]])

    def test_all_printers_paused_and_aborted(self):
        self.queue_job()
        self.press("Alle fortsetzen")
        self.assertFalse(self.printers.state(ZEBRA["uid"])["held"])
        self.press("Alle anhalten")
        self.assertTrue(self.printers.state(ZEBRA["uid"])["held"])
        aborted = []
        self.printers.abort = lambda uid=None, by="display": aborted.append(uid)
        self.press("Alle abbrechen")
        self.assertEqual(aborted, [])  # asks on the button first
        self.press("Wirklich alle abbrechen?")
        self.assertEqual(aborted, [None])

    def test_printer_page_sets_labels_and_ribbon(self):
        self.press("Drucker")
        self.touch.show_printer(ZEBRA["uid"])
        self.assertIn("Farbband", self.texts())
        self.assertIn("keins gesetzt", self.texts())
        self.press("Etiketten wählen")
        self.assertEqual(self.labels(), ["Abbrechen", "✓ 57 × 32", "60 × 30"])
        self.press("60 × 30")
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 2)])
        self.press("Farbband wählen")
        self.press("Wachsband 110 mm, schwarz")
        self.assertEqual(self.link.loaded[-1], (ZEBRA["uid"], 5))
        self.press("‹ Zurück")
        self.assertIsNone(self.touch.detail)

    def test_a_long_list_of_labels_scrolls_in_its_dialog(self):
        self.link.settings[ZEBRA["uid"]]["media"] = [{"id": number, "name": f"Etiketten {number}"}
                                                     for number in range(1, 13)]
        self.touch.show_tab("printers")
        self.touch.show_printer(ZEBRA["uid"])
        self.press("Etiketten wählen")
        frame = self.touch.update()
        left, top, width, height = frame.choices_area
        self.assertGreater(frame.choices_height, height)
        self.assertEqual(frame.choices_scroll, 0)  # the chosen one (the first) is in sight
        self.assertFalse(self.touch.tap(left + width // 2, top + height + 4))  # below the list: hidden entries
        self.touch.drag(-10_000)
        self.press("Etiketten 12")
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 12)])
        self.assertEqual(self.touch.dialogs, [])
        self.link.settings[ZEBRA["uid"]]["loaded"] = 12  # (the server's answer)
        self.press("Etiketten wählen")  # opened again: scrolled to the chosen one
        self.assertGreater(self.touch.update().choices_scroll, 0)
        self.touch.drag(10_000)
        self.press("Etiketten 1")
        self.assertEqual(self.link.loaded[-1], (ZEBRA["uid"], 1))

    def test_pairing_is_asked(self):
        request = FakeRequest()
        self.touch.ask(request)
        self.assertIn("Bluetooth-Drucker gefunden", self.texts())
        self.press("Koppeln")
        self.assertEqual((request.answer, self.touch.questions, self.touch.dialogs), ("yes", [], []))
        declined = FakeRequest()
        self.touch.ask(declined)
        self.press("Nein")
        self.assertEqual(declined.answer, "no")

    def test_bluetooth_printers_searched_paired_and_unpaired(self):
        self.press("Bluetooth")
        self.press("Drucker suchen")
        self.press("Koppeln")
        self.press("Entkoppeln")
        self.assertIn("PT-P710BT6522 entkoppeln?", self.texts())
        self.press("Ja, entkoppeln")
        self.assertEqual(self.bluetooth.calls, ["search", ("pair", "11:22:33:44:55:66"),
                                                ("unpair", "A1:B2:C3:D4:E5:F6")])
        self.touch.attach(self.printers, [self.link], None)
        self.assertIn("aus (config.json)", self.texts())

    def test_the_first_touch_after_the_backlight_went_off_only_lights_it(self):
        self.assertTrue(self.touch.backlight_on())
        self.now += 601
        self.assertFalse(self.touch.backlight_on())
        self.touch.lit = False
        self.assertFalse(self.touch.tap(400, 448))  # on the tab "Verbindung" … but only lights the screen
        self.assertEqual(self.touch.tab, "queue")
        self.assertTrue(self.touch.backlight_on())
        self.queue_job()  # jobs keep it lit
        self.now += 601
        self.assertTrue(self.touch.backlight_on())

    def test_long_pages_scroll(self):
        self.link.waiting = [{"printer": ZEBRA["uid"], "medium": 2, "material": f"Etiketten {number}", "jobs": 1}
                             for number in range(8)]
        frame = self.touch.update()
        self.assertGreater(frame.height, 480)
        self.touch.drag(-10_000)
        self.assertEqual(self.touch.scroll["queue"], frame.height - (480 - 48 - 64))
        self.touch.drag(10_000)
        self.assertEqual(self.touch.scroll["queue"], 0)

    def test_a_page_scrolls_by_its_own_length_right_after_it_is_opened(self):
        for number in range(8):
            self.queue_job(job_id=number)
        self.touch.update()  # the queue drawn
        self.touch.show_tab("printers")
        self.touch.show_printer(ZEBRA["uid"])
        self.touch.drag(-10_000)  # before it was drawn
        frame = self.touch.layout()
        self.assertEqual(self.touch.scroll[("printer", ZEBRA["uid"])], frame.height - (480 - 48 - 64))

    def test_text_is_wrapped_to_the_width(self):
        lines = self.touch.wrap("eins zwei drei vier fünf sechs", 100, 20)
        self.assertEqual(lines, ["eins zwei", "drei vier", "fünf", "sechs"])


class AgentDisplayTests(SimpleTestCase):
    def config(self, **values):
        return {**agent.DEFAULTS, **values}

    def test_a_touch_screen_first_then_the_piface_display(self):
        screen = mock.Mock()
        with mock.patch("label_printing.devices.screen.TouchScreen", return_value=screen) as found:
            touch = agent.open_display(self.config(screen_rotation=180), "pi-lager")
        self.assertIsInstance(touch, Touch)
        self.assertEqual((touch.screen, touch.version), (screen, agent.VERSION))
        found.assert_called_once_with(rotation=180)
        from ..devices.screen import NoScreen
        from ..panel import Panel

        with mock.patch("label_printing.devices.screen.TouchScreen", side_effect=NoScreen("no display")), \
                mock.patch("label_printing.devices.piface.PiFaceCAD") as piface:
            self.assertIsInstance(agent.open_display(self.config(), "pi-lager"), Panel)
            self.assertIsNone(agent.open_display(self.config(display="touch"), "pi-lager"))
        piface.assert_called_once()
        self.assertIsNone(agent.open_display(self.config(display="none"), "pi-lager"))

    def test_pairings_are_kept_on_a_change(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {"RUNTIME_DIRECTORY": folder}):
                agent.keep_pairings()
            self.assertTrue(os.path.exists(os.path.join(folder, "keep-bluetooth")))
        with mock.patch.dict(os.environ, {}, clear=True):
            agent.keep_pairings()  # not under systemd: nothing to do

    def test_printers_found_by_bluetooth(self):
        found = bluetooth.Bluetooth()
        found.paired = {"A1:B2:C3:D4:E5:F6": {"product": "PT-P710BT6522"}}
        found.seen = {"11:22:33:44:55:66": "PT-P910BT0815", "AA:BB:CC:DD:EE:01": "PT-P300BT1234",
                      "AA:BB:CC:DD:EE:02": "PT-E560BT9"}
        found.declined, found.pairing = {"AA:BB:CC:DD:EE:01"}, {"AA:BB:CC:DD:EE:02"}
        self.assertEqual([(entry["name"], entry["state"]) for entry in found.found()], [
            ("PT-E560BT9", "pairing"), ("PT-P300BT1234", "declined"), ("PT-P710BT6522", "paired"),
            ("PT-P910BT0815", "new")])
        with mock.patch.object(found, "call_soon"):
            found.pair("AA:BB:CC:DD:EE:01")  # declined before, paired on the touch screen now
        self.assertNotIn("AA:BB:CC:DD:EE:01", found.declined)
