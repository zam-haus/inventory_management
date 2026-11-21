"""The print agent's touch screen (touch.py), without screen and pygame: what it lays out and what taps do."""
import base64
import io
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

from .. import agent
from ..agent import Printers, Task
from ..devices import bluetooth
from ..touch import CONTENT_BOTTOM, CONTENT_TOP, Touch
from .test_station import SERVERS, ZEBRA, FakeConnection, FakeLink, FakeRequest


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
        self.connection = FakeConnection(self.link, SERVERS)
        self.touch.attach(self.printers, self.connection, self.bluetooth)
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
                    if items is frame.content:
                        self.assertTrue(CONTENT_TOP <= y < CONTENT_BOTTOM, f"{label!r} is scrolled out of sight")
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
        self.assertIn("USB · ✓ bereit, 57 × 32 · kein Farbband gesetzt", self.texts())  # labels and ribbon loaded
        self.press("Verbindung")
        self.assertIn("✓ verbunden", self.texts())
        self.assertIn("192.0.2.23", self.texts())
        self.assertIn("5.2", self.texts())
        self.press("Bluetooth")
        self.assertIn("A1:B2:C3:D4:E5:F6 · gekoppelt", self.texts())

    def test_labels_waiting_come_first_and_are_confirmed(self):
        self.link.waiting = [{"printer": ZEBRA["uid"], "medium": 2, "material": "60 × 30",
                              "loaded": "57 × 32", "jobs": 2}]
        self.assertIn("Aufträge (1!)", self.labels())
        self.assertIn("! Zebra Lager", self.texts())
        self.assertEqual(self.touch.alerts(self.touch.reports())[0].text,
                         "57 × 32 herausnehmen. 60 × 30 einlegen. 2 Aufträge warten.")
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

    def test_a_ribbon_to_change_with_the_labels(self):
        def loaded_labels_the_ribbon_does_not_suit(uid, medium):
            self.link.settings[uid]["ribbon_problem"] = "Das Farbband passt nicht zu den Etiketten."
            return True
        self.link.set_loaded = loaded_labels_the_ribbon_does_not_suit
        self.link.settings[ZEBRA["uid"]]["media"][1]["ribbon_change"] = True
        self.press("Drucker")
        self.press("Etiketten")
        self.assertIn("60 × 30 · Farbband wechseln", self.labels())
        self.press("60 × 30 · Farbband wechseln")
        self.assertIn("Welches Farbband ist eingelegt?", self.texts())  # asked at once
        self.assertIn("Wachsband 110 mm, schwarz", self.labels())

    def test_only_the_ribbon_to_change(self):
        self.link.waiting = [{"printer": ZEBRA["uid"], "medium": None, "material": "", "ribbon_out": "Wachsband 84 mm",
                              "ribbon_in": "Harzband 111 mm", "jobs": 1, "ribbon_problem": "passt nicht"}]
        alert, = self.touch.alerts(self.touch.reports())
        self.assertEqual((alert.kind, alert.text), ("ribbon", "Farbband Wachsband 84 mm herausnehmen. "
                                                              "Farbband Harzband 111 mm einlegen. 1 Auftrag warten."))
        self.assertIn("Farbband wählen", self.labels())

    def test_one_job_cancelled(self):
        self.queue_job()
        aborted = []
        self.printers.abort = lambda uid=None, by="display", job_id=None: aborted.append((uid, job_id))
        self.press("✕")
        self.assertIn("#7 abbrechen?", self.texts())
        self.press("Ja, abbrechen")
        self.assertEqual(aborted, [(ZEBRA["uid"], 7)])

    def test_waiting_jobs_count_down_wait_longer_and_are_cancelled(self):
        self.link.offered = [{"id": 9, "subject": "R303.b Fach b", "label": "Fach (60 × 30)", "material": "60 × 30",
                              "printer": ZEBRA["uid"], "until": self.now + 125},
                             {"id": 10, "subject": "Atrium", "label": "Ort (18-mm-Band)", "material": "18-mm-Band",
                              "printer": "usb-04f9-2085-B1", "printers": ["usb-04f9-2085-B1", ZEBRA["uid"]],
                              "until": self.now + 300}]
        self.assertIn("Warten auf einen Drucker", self.texts())
        self.assertIn("60 × 30 einlegen · Zebra Lager", self.texts())  # what to do first, the job below
        self.assertIn("18-mm-Band einlegen · usb-04f9-2085-B1 oder Zebra Lager", self.texts())  # any of them
        self.link.offered = self.link.offered[:1]
        self.assertIn("#9 Fach (60 × 30) · R303.b Fach b", self.texts())
        self.press("noch 2:05")
        self.now += 5
        self.assertIn("noch 2:00", self.labels())
        self.press("✕")
        self.press("Ja, abbrechen")
        self.assertEqual(self.link.calls, [("extend", 9), ("cancel", 9)])
        self.assertNotIn("Warten auf einen Drucker", self.texts())

    def test_finished_jobs_and_a_job_page_with_previews(self):
        """The job list goes on with the finished jobs; a job tapped shows its page: what it is, its state, previews
        of its labels with how many each, and it is printed again from there."""
        image = io.BytesIO()
        Image.new("RGB", (120, 64), "white").save(image, format="PNG")
        self.link.recent = [{"id": 31, "subject": "R303.b Fach b", "label": "Fach", "printer": ZEBRA["uid"],
                             "status": "done", "finished": self.now - 300},
                            {"id": 30, "subject": "Atrium", "label": "Ort", "printer": "", "status": "expired",
                             "message": "Kein Drucker konnte ihn rechtzeitig drucken.", "finished": self.now - 4000}]
        texts = self.texts()
        self.assertIn("Erledigt", texts)
        self.assertIn("✓ #31 R303.b Fach b", texts)
        self.assertIn("Fach · Zebra Lager · gedruckt vor 5 min", texts)
        self.assertIn("✗ #30 Atrium", texts)
        self.link.detail = {"job": {"id": 31, "subject": "R303.b Fach b", "label": "Fach", "printer": ZEBRA["uid"],
                                    "material": "57 × 32", "status": "done", "copies": 2},
                            "labels": [{"subject": "R303.b Fach b", "count": 2,
                                        "image": base64.b64encode(image.getvalue()).decode()}],
                            "problem": "", "more": 0}
        self.press("Auftrag #31")
        texts = self.texts()
        self.assertIn("#31 Fach", texts)
        self.assertIn("gedruckt vor 5 min", texts)
        self.assertIn("57 × 32", texts)
        self.assertIn("× 2", texts)
        picture, = self.items("image")
        self.assertEqual((picture.w, picture.h), (120, 64))
        self.press("Nochmal drucken")
        self.assertEqual(self.link.calls, [("detail", 31), ("reprint", 31)])
        self.assertEqual(self.touch.note, "nochmal aufgegeben als #131")
        self.press("‹ Zurück")
        self.assertIn("Erledigt", self.texts())
        self.link.detail = None  # the server not reached: why, on the page
        self.press("Auftrag #30")
        self.assertIn("Server nicht erreichbar", self.texts())
        self.assertIn("Kein Drucker konnte ihn rechtzeitig drucken.", self.texts())

    def test_quick_buttons_in_the_printer_list(self):
        brother = {"uid": "usb-04f9-2085-B1", "device": "/dev/usb/lp1", "language": "ptouch", "product": "PT-P900W",
                   "dpi": 360, "status": {"media_width_mm": 12, "tape_color": "weiß", "text_color": "schwarz"}}
        self.printers = Printers([ZEBRA, brother], find=lambda: [])
        self.printers.scan()
        self.printers.remember(brother["uid"], brother["status"])
        self.touch.attach(self.printers, self.connection, self.bluetooth)
        self.link.settings[brother["uid"]] = {"name": "P-touch Werkstatt", "active": True, "language": "ptouch",
                                              "tapes": ["TZe-231"]}
        cut = []
        self.printers.cut = lambda uid: cut.append(uid) or agent.Result("done")
        self.press("Drucker")
        self.assertIn("USB · ✓ bereit, 12 mm schwarz auf weiß (TZe-231)", self.texts())
        self.press("Abschneiden")
        self.assertEqual((cut, self.touch.note), ([brother["uid"]], "abgeschnitten"))
        self.press("Etiketten")  # the Zebra's
        self.assertEqual(self.labels(), ["Abbrechen", "✓ 57 × 32", "60 × 30"])

    def test_printers_expected_but_not_found(self):
        self.link.settings["usb-0a5f-0081-GONE"] = {"name": "Zebra Büro", "active": True, "language": "zpl"}
        self.link.settings["usb-0a5f-0081-OFF"] = {"name": "Zebra alt", "active": False, "language": "zpl"}
        self.press("Drucker")
        self.assertIn("Zebra Büro", self.texts())
        self.assertIn("– · ✗ nicht gefunden (Kabel, Strom, Bluetooth?)", self.texts())
        self.assertNotIn("Zebra alt", self.texts())  # not expected: inactive
        self.touch.show_printer("usb-0a5f-0081-GONE")
        self.assertNotIn("Anhalten", self.labels())

    def test_offsets_after_a_calibration_label(self):
        self.link.settings[ZEBRA["uid"]].update(offset_x=0, offset_y=2)
        self.touch.show_tab("printers")
        self.touch.show_printer(ZEBRA["uid"])
        self.touch.drag(-10_000)
        self.assertIn("y 2", self.texts())
        buttons = [item for item in self.items("button") if item.label in ("−", "+")]
        self.assertEqual(len(buttons), 4)  # x and y on a Zebra
        buttons[3].action()  # y +
        buttons[3].action()
        buttons[0].action()  # x −
        self.assertEqual(self.link.calls, [("offsets", ZEBRA["uid"], 0, 3), ("offsets", ZEBRA["uid"], 0, 4),
                                           ("offsets", ZEBRA["uid"], -1, 4)])
        self.assertIn("y 4", self.texts())

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
        self.assertIn("57 × 32 · kein Farbband gesetzt", self.texts())  # "Eingelegt": labels and ribbon
        self.press("Etiketten wählen")
        self.assertEqual(self.labels(), ["Abbrechen", "✓ 57 × 32", "60 × 30"])
        self.press("60 × 30")
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], 2)])
        self.press("Farbband wählen")
        self.press("Wachsband 110 mm, schwarz")
        self.assertEqual(self.link.loaded[-1], (ZEBRA["uid"], 5))
        self.press("‹ Zurück")
        self.assertIsNone(self.touch.detail)

    def test_printer_page_prints_test_and_calibration_labels(self):
        self.touch.show_tab("printers")
        self.touch.show_printer(ZEBRA["uid"])
        self.touch.drag(-10_000)  # below the Zebra's buttons
        self.press("Testetikett drucken")
        self.press("Kalibrieretikett drucken")
        self.assertEqual(self.link.asked, [(ZEBRA["uid"], "test"), (ZEBRA["uid"], "calibration")])
        self.assertIn("Kalibrieretikett kommt", self.texts())
        self.link.refusal = "Er nimmt kein vorrätiges Etikettenmaterial. Markiere Etikettenmaterial als vorrätig."
        self.press("Testetikett drucken")
        self.assertIn("Testetikett nicht gedruckt", self.texts())  # the reason in full, in a dialog
        self.assertLessEqual(self.touch.note_until, self.now)  # no "fordere an ..." behind it
        self.press("OK")
        self.assertEqual(self.touch.dialogs, [])
        self.link.settings[ZEBRA["uid"]]["active"] = False
        self.assertNotIn("Testetikett drucken", self.labels())

    def test_a_ribbon_that_does_not_suit_the_labels(self):
        self.link.settings[ZEBRA["uid"]].update(ribbon=5, ribbon_problem="Das Farbband passt nicht zu den Etiketten.")
        self.assertIn("! Zebra Lager", self.texts())
        self.press("Farbband wählen")
        self.press("kein Farbband")
        self.assertEqual(self.link.loaded, [(ZEBRA["uid"], None)])

    def test_another_server_is_chosen_on_the_connection_tab(self):
        self.press("Verbindung")
        self.assertIn("inventar.zam.haus", self.texts())
        self.press("Stattdessen für 192.0.2.10 arbeiten")
        self.press("Ja, wechseln")
        self.assertEqual(self.connection.switched, [1])

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
        self.touch.attach(self.printers, FakeConnection(self.link), None)
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

    def test_the_touch_screen_if_there_is_one(self):
        screen = mock.Mock()
        with mock.patch("label_printing.devices.screen.TouchScreen", return_value=screen) as found:
            touch = agent.open_display(self.config(screen_rotation=180), "pi-lager")
        self.assertIsInstance(touch, Touch)
        self.assertEqual((touch.screen, touch.version), (screen, agent.VERSION))
        found.assert_called_once_with(rotation=180)
        from ..devices.screen import NoScreen

        with mock.patch("label_printing.devices.screen.TouchScreen", side_effect=NoScreen("no display")):
            self.assertIsNone(agent.open_display(self.config(), "pi-lager"))
            self.assertIsNone(agent.open_display(self.config(display="touch"), "pi-lager"))
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
