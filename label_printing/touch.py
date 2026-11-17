"""
The print agent's touch screen (Raspberry Pi Touch Display, 800 × 480; drawn with pygame by devices/screen.py).
Plain Python, no Django and no pygame here: this module lays out what is shown as items (texts, boxes, buttons)
and carries out taps; the screen draws them. The texts are German, like the people standing at the printers.

Four tabs at the bottom:
* Aufträge: what needs someone (labels to load in a printer, with "Sind eingelegt" for a Zebra; a ribbon that
  does not suit a Zebra's labels), then each printer's jobs (the one printing with how many labels went out) with
  pause / go on and abort; "Alle anhalten" and "Alle abbrechen" for all printers;
* Drucker: the printers and their state; a printer's page shows how it is connected, what is loaded and its
  jobs, pauses or aborts them and sets the labels and the ribbon loaded in a Zebra;
* Verbindung: the server (connected, or why not) and the others configured, to work for one of them instead
  (until the agent starts again), the network addresses, Bluetooth and the agent's version;
* Bluetooth: the printers paired and found, search now, pair and unpair.

Pairing a printer that was found is asked in a dialog, which stays until answered. Long pages scroll by dragging.
The backlight goes off after backlight_timeout seconds without a touch, unless something needs someone; the
first touch then only lights it.
"""
import time

from .station import BLUETOOTH, Station, addresses

WIDTH, HEIGHT = 800, 480
HEADER, TABS = 48, 64
CONTENT_TOP, CONTENT_BOTTOM = HEADER, HEIGHT - TABS
PAD = 12
ROW = 64  # the height of a button row: buttons a finger hits
TAP_SLOP = 12  # a touch moving less than this is a tap, else it scrolls

TABS_SHOWN = (("queue", "Aufträge"), ("printers", "Drucker"), ("connection", "Verbindung"), ("bluetooth", "Bluetooth"))
BLUETOOTH_STATES = {"paired": "gekoppelt", "pairing": "koppelt ...", "declined": "nicht gekoppelt", "new": "gefunden"}


class Text:
    """One line (cut with … if too long); size in pixels; colour a name of the screen's palette."""
    kind = "text"

    def __init__(self, x, y, w, text, size=20, color="text", bold=False, align="left"):
        self.x, self.y, self.w, self.text, self.size = x, y, w, text, size
        self.color, self.bold, self.align = color, bold, align


class Box:
    kind = "box"

    def __init__(self, x, y, w, h, color="card"):
        self.x, self.y, self.w, self.h, self.color = x, y, w, h, color


class Button:
    """style: "normal", "primary", "danger", "tab", "tab_active", "flat"; without action it is shown disabled."""
    kind = "button"

    def __init__(self, x, y, w, h, label, action=None, style="normal", size=20):
        self.x, self.y, self.w, self.h, self.label, self.action = x, y, w, h, label, action
        self.style, self.size = style, size

    def hit(self, x, y):
        return self.action is not None and self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


class Frame:
    """What the screen shows: fixed items, and content items (y from the content's top) that scroll in the
    content area between header and tabs."""

    def __init__(self):
        self.fixed, self.content, self.overlay, self.height = [], [], [], 0
        # a dialog's choices (y from the list's top) scroll in their own area (x, y, w, h) inside the dialog
        self.choices, self.choices_area, self.choices_height, self.choices_scroll = [], None, 0, 0


class Dialog:
    """A box over everything: a title, a text and buttons ((label, action, style)); an action returning a Dialog
    opens it, else the dialog closes. With choices it is a list to choose from."""

    def __init__(self, title, text="", buttons=(), choices=(), question=None):
        self.title, self.text, self.buttons, self.choices = title, text, list(buttons), list(choices)
        self.question = question  # a pairing request: answered when the dialog closes
        self.scroll = 0  # pixels the choices are scrolled (a long list scrolls by dragging)


def read_only():
    """Whether the system runs read-only (raspi-config's overlay file system, ops/raspberry-pi/update.sh)."""
    try:
        with open("/proc/cmdline") as file:
            return "overlayroot=tmpfs" in file.read()
    except OSError:
        return False


def plural(count, one, many):
    return f"{count} {one if count == 1 else many}"


class Touch(Station):
    def __init__(self, screen, hostname, backlight_timeout=600, version="", clock=time.monotonic, addresses=addresses,
                 measure=None):
        super().__init__(hostname, clock=clock, addresses=addresses)
        self.screen, self.backlight_timeout, self.version = screen, backlight_timeout, version
        self.measure = measure or (screen.measure if screen is not None else lambda text, size, bold=False:
                                   len(text) * size * 0.55)
        self.tab, self.detail, self.dialogs = "queue", None, []
        self.scroll = {}  # view → pixels scrolled
        self.last_input = clock()
        self.lit = True
        self.confirm_all_until = 0.0
        self.frame = None

    # ------------------------------------------------------------ text

    def wrap(self, text, width, size=20, bold=False):
        """The text in lines that fit `width` (words kept whole where they fit)."""
        lines = []
        for paragraph in str(text).split("\n"):
            line = ""
            for word in paragraph.split(" "):
                candidate = f"{line} {word}" if line else word
                if not line or self.measure(candidate, size, bold) <= width:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def paragraph(self, items, x, y, width, text, size=20, color="text", bold=False, gap=4):
        """Text over as many lines as it needs; the y below it."""
        for line in self.wrap(text, width, size, bold):
            items.append(Text(x, y, width, line, size, color, bold))
            y += size + gap
        return y

    # ------------------------------------------------------------ state in words

    def reports(self):
        return self.printers.report() if self.printers else {}

    def sorted_printers(self, reports):
        return sorted(reports.items(), key=lambda item: self.printer_name(*item).lower())

    def connection_of(self, report):
        device = str(report.get("device", ""))
        if device.startswith("bt://"):
            return "Bluetooth"
        if device.startswith("tcp://"):
            return "Netzwerk " + device[len("tcp://"):]
        return "USB"

    def job_text(self, job):
        pages = job.get("pages", 1)
        text = f"#{job['id']}"
        if job.get("subject"):
            text += f" {job['subject']}"
        if job.get("printing"):
            text += f" · {job.get('sent', 0)}/{pages} Etiketten"
        else:
            text += f" · {plural(pages, 'Etikett', 'Etiketten')}"
        return text

    def color_of(self, text):
        return "error" if text.startswith("✗") else "warn" if text.startswith(("⏸", "!")) else (
            "ok" if text.startswith(("✓", "▶")) else "muted")

    # ------------------------------------------------------------ layout

    def layout(self):
        frame = Frame()
        reports = self.reports()
        alerts = self.alerts(reports)
        self.header(frame, reports)
        if self.tab == "printers" and self.detail is not None and self.detail in reports:
            self.printer_page(frame, self.detail, reports[self.detail])
        elif self.tab == "printers":
            self.detail = None
            self.printers_page(frame, reports)
        elif self.tab == "connection":
            self.connection_page(frame)
        elif self.tab == "bluetooth":
            self.bluetooth_page(frame)
        else:
            self.queue_page(frame, reports, alerts)
        self.tab_bar(frame, alerts)
        self.note_bar(frame)
        self.dialog(frame)
        self.frame = frame
        return frame

    def header(self, frame, reports):
        frame.fixed.append(Box(0, 0, WIDTH, HEADER, "header"))
        network = self.network()
        frame.fixed.append(Text(PAD, 12, 420, f"{self.hostname} · {network[0][1] if network else 'kein Netz'}", 22,
                                bold=True))
        connected = self.link is not None and self.link.state["code"] == "ok"
        frame.fixed.append(Text(440, 13, 200, "✓ Server" if connected else "✗ Server", 20,
                                "ok" if connected else "error", align="right"))
        frame.fixed.append(Text(660, 12, WIDTH - 660 - PAD, time.strftime("%H:%M"), 22, align="right"))

    def tab_bar(self, frame, alerts):
        width = WIDTH // len(TABS_SHOWN)
        for index, (key, label) in enumerate(TABS_SHOWN):
            if key == "queue" and alerts:
                label += f" ({len(alerts)}!)"
            frame.fixed.append(Button(index * width, CONTENT_BOTTOM, width, TABS, label,
                                      lambda key=key: self.show_tab(key),
                                      "tab_active" if key == self.tab else "tab", 22))

    def note_bar(self, frame):
        with self.lock:
            note = self.note if self.clock() < self.note_until else ""
        if note:
            frame.fixed.append(Box(PAD, CONTENT_BOTTOM - 52, WIDTH - 2 * PAD, 44, "note"))
            frame.fixed.append(Text(2 * PAD, CONTENT_BOTTOM - 42, WIDTH - 4 * PAD, note, 22, bold=True))

    def card(self, items, y, height, color="card"):
        items.append(Box(PAD, y, WIDTH - 2 * PAD, height, color))

    def queue_page(self, frame, reports, alerts):
        items, y, inner = frame.content, PAD, WIDTH - 4 * PAD
        held = any(self.printers.state(uid)["held"] for uid in reports) if reports else False
        busy = any(self.printers.jobs(uid) for uid in reports) if reports else False
        half = (WIDTH - 3 * PAD) // 2
        items.append(Button(PAD, y, half, ROW - 8, "Alle fortsetzen" if held else "Alle anhalten",
                            self.pause_all if reports else None, "normal"))
        confirming = self.clock() < self.confirm_all_until
        items.append(Button(2 * PAD + half, y, half, ROW - 8,
                            "Wirklich alle abbrechen?" if confirming else "Alle abbrechen",
                            self.abort_all if busy else None, "danger"))
        y += ROW + 4
        for alert in alerts:
            lines = self.wrap(alert.text, inner, 20)
            buttons = alert.kind == "ribbon" or alert.medium
            height = 16 + 28 + len(lines) * 24 + (ROW if buttons else 0) + 4
            self.card(items, y, height, "alert")
            items.append(Text(2 * PAD, y + 10, inner, "! " + alert.name, 22, "warn", bold=True))
            text_y = self.paragraph(items, 2 * PAD, y + 40, inner, alert.text, 20)
            if alert.kind == "waiting" and alert.medium:
                items.append(Button(2 * PAD, text_y + 4, 280, ROW - 12, "Sind eingelegt",
                                    lambda alert=alert: self.set_loaded(alert.uid, alert.medium),
                                    "primary"))
            elif alert.kind == "ribbon":
                items.append(Button(2 * PAD, text_y + 4, 280, ROW - 12, "Farbband wählen",
                                    lambda alert=alert: self.open(self.ribbon_dialog(alert.uid)),
                                    "primary"))
            y += height + PAD
        shown = 0
        for uid, report in self.sorted_printers(reports):
            jobs = self.printers.jobs(uid)
            state = self.printers.state(uid)
            if not jobs and not state["held"]:
                continue
            shown += 1
            height = 16 + 30 + max(1, len(jobs)) * 28 + ROW
            self.card(items, y, height)
            items.append(Text(2 * PAD, y + 10, inner // 2, self.printer_name(uid, report), 22, bold=True))
            status = self.printer_text(uid, report)
            items.append(Text(2 * PAD + inner // 2, y + 12, inner // 2, status, 20, self.color_of(status),
                              align="right"))
            row_y = y + 46
            for job in jobs:
                mark = "⏸ " if job["paused"] and job["printing"] else "▶ " if job["printing"] else "· "
                items.append(Text(2 * PAD, row_y, inner, mark + self.job_text(job), 20,
                                  "text" if job["printing"] else "muted"))
                row_y += 28
            if not jobs:
                items.append(Text(2 * PAD, row_y, inner, "keine Aufträge; startet keine neuen", 20, "muted"))
                row_y += 28
            self.printer_buttons(items, uid, state, bool(jobs), row_y + 2)
            y += height + PAD
        if not shown and not alerts:
            printing = "Keine Aufträge" if reports else "Keine Drucker: USB- oder Bluetooth-Drucker anschließen"
            items.append(Text(PAD, y + 20, WIDTH - 2 * PAD, printing, 24, "muted", align="center"))
            y += 60
        frame.height = y

    def printer_buttons(self, items, uid, state, has_jobs, y):
        width = 230
        if state["held"] or state["paused"]:
            items.append(Button(2 * PAD, y, width, ROW - 12, "Fortsetzen",
                                lambda: self.do(self.printers.resume, uid, note="fortgesetzt"), "primary"))
        else:
            items.append(Button(2 * PAD, y, width, ROW - 12, "Pausieren" if has_jobs else "Anhalten",
                                lambda: self.do(self.printers.pause, uid, note="angehalten")))
        if has_jobs:
            items.append(Button(3 * PAD + width, y, width, ROW - 12, "Abbrechen",
                                lambda: self.open(Dialog(f"{self.printer_name(uid)}: alle Aufträge abbrechen?",
                                                         "Was schon gedruckt ist, bleibt gedruckt.", [
                                                             ("Ja, abbrechen", lambda: self.abort(uid), "danger"),
                                                             ("Nein", None, "normal")])), "danger"))

    def printers_page(self, frame, reports):
        items, y, inner = frame.content, PAD, WIDTH - 4 * PAD
        for uid, report in self.sorted_printers(reports):
            status = self.printer_text(uid, report)
            self.card(items, y, 76)
            items.append(Button(PAD, y, WIDTH - 2 * PAD, 76, "", lambda uid=uid: self.show_printer(uid), "flat"))
            items.append(Text(2 * PAD, y + 10, inner - 40, self.printer_name(uid, report), 22, bold=True))
            items.append(Text(WIDTH - 2 * PAD - 30, y + 24, 30, "›", 28, "muted", align="right"))
            items.append(Text(2 * PAD, y + 42, inner - 40, f"{self.connection_of(report)} · {status}", 20,
                              self.color_of(status)))
            y += 76 + PAD
        if not reports:
            items.append(Text(PAD, y + 20, WIDTH - 2 * PAD, "Keine Drucker: USB- oder Bluetooth-Drucker anschließen",
                              24, "muted", align="center"))
            y += 60
        frame.height = y

    def printer_page(self, frame, uid, report):
        items, y, inner = frame.content, PAD, WIDTH - 4 * PAD
        state = self.printers.state(uid)
        jobs = self.printers.jobs(uid)
        status = self.printer_text(uid, report)
        info = report.get("info") or {}
        items.append(Button(PAD, y, 160, ROW - 12, "‹ Zurück", self.back, "normal"))
        items.append(Text(PAD + 176, y + 12, WIDTH - 176 - 2 * PAD, self.printer_name(uid, report), 26, bold=True))
        y += ROW
        lines = [("Zustand", status), ("Verbindung", self.connection_of(report)),
                 ("Modell", " ".join(str(part) for part in (info.get("manufacturer"), info.get("product") or
                                                            info.get("model")) if part) or "–")]
        loaded = self.loaded_text(uid, report.get("status") or {})
        if loaded:
            lines.append(("Eingelegt", loaded))
        settings = self.settings(uid)
        if settings.get("language") == "zpl":
            ribbon = next((entry["name"] for entry in settings.get("ribbons", []) if entry["id"] == settings.get("ribbon")),
                          None)
            lines.append(("Farbband", ribbon or "keins gesetzt"))
        for label, value in lines:
            items.append(Text(2 * PAD, y, 170, label, 20, "muted"))
            y = self.paragraph(items, 2 * PAD + 180, y, inner - 180, value, 20,
                               self.color_of(value) if label == "Zustand" else "text")
            y += 4
        y += 4
        self.printer_buttons(items, uid, state, bool(jobs), y)
        y += ROW
        if settings.get("language") == "zpl" and settings.get("active"):
            x = 2 * PAD
            if settings.get("media"):
                items.append(Button(x, y, 360, ROW - 12, "Etiketten wählen", lambda: self.open(self.media_dialog(uid))))
                x += 360 + PAD
            if settings.get("ribbons"):
                items.append(Button(x, y, 360, ROW - 12, "Farbband wählen", lambda: self.open(self.ribbon_dialog(uid))))
            y += ROW
        for index, (label, which) in enumerate(self.own_label_entries(uid)):
            items.append(Button(2 * PAD + index % 2 * (360 + PAD), y, 360, ROW - 12, label + " drucken",
                                lambda which=which: self.print_own_label(uid, which)))
            y += ROW if index % 2 else 0
        if jobs:
            items.append(Text(2 * PAD, y, inner, "Aufträge", 22, bold=True))
            y += 32
            for job in jobs:
                mark = "▶ " if job["printing"] else "· "
                items.append(Text(2 * PAD, y, inner, mark + self.job_text(job), 20,
                                  "text" if job["printing"] else "muted"))
                y += 28
        frame.height = y + PAD

    def connection_page(self, frame):
        items, y, inner = frame.content, PAD, WIDTH - 4 * PAD
        items.append(Text(PAD, y, inner, "Server", 22, bold=True))
        y += 34
        link = self.link
        if link is not None:
            text = self.link_text(link)
            lines = self.wrap(text, inner, 20)
            height = 46 + len(lines) * 24
            self.card(items, y, height)
            items.append(Text(2 * PAD, y + 10, inner, self.server_name(link.server), 22, bold=True))
            self.paragraph(items, 2 * PAD, y + 40, inner, text, 20, self.color_of(text))
            y += height + PAD
        else:
            items.append(Text(PAD, y, inner, "kein Server (config.json)", 20, "error"))
            y += 32
        servers = self.connection.servers if self.connection is not None else []
        for index, server in enumerate(servers):
            if index == self.connection.index:
                continue
            name = self.server_name(server["url"])
            items.append(Button(PAD, y, WIDTH - 2 * PAD, ROW - 12, f"Stattdessen für {name} arbeiten",
                                lambda index=index, name=name: self.open(Dialog(
                                    f"Für {name} arbeiten?",
                                    "Bis zum nächsten Neustart des Agenten; danach wieder für den ersten Server.",
                                    [("Ja, wechseln", lambda: self.switch_server(index), "primary"),
                                     ("Nein", None, "normal")]))))
            y += ROW
        items.append(Text(PAD, y + 4, inner, "Netzwerk", 22, bold=True))
        y += 38
        network = self.network()
        for interface, address in network:
            items.append(Text(2 * PAD, y, 160, interface, 20, "muted"))
            items.append(Text(2 * PAD + 170, y, inner - 170, address, 20))
            y += 28
        if not network:
            items.append(Text(2 * PAD, y, inner, "keine Adresse (Kabel, WLAN?)", 20, "error"))
            y += 28
        y += 8
        items.append(Text(PAD, y, inner, "Druckagent", 22, bold=True))
        y += 34
        bluetooth = self.bluetooth_text()
        for label, value in (("Name", self.hostname), ("Version", self.version or "–"), ("Bluetooth", bluetooth),
                             ("System", "schreibgeschützt (schont die SD-Karte)" if read_only() else "beschreibbar")):
            items.append(Text(2 * PAD, y, 160, label, 20, "muted"))
            y = self.paragraph(items, 2 * PAD + 170, y, inner - 170, value, 20)
            y += 4
        frame.height = y + PAD

    def bluetooth_text(self):
        if self.bluetooth is None:
            return "aus (config.json)"
        text = BLUETOOTH.get(self.bluetooth.status, self.bluetooth.status)
        return text + (f": {self.bluetooth.problem}" if self.bluetooth.problem else "")

    def bluetooth_page(self, frame):
        items, y, inner = frame.content, PAD, WIDTH - 4 * PAD
        status = self.bluetooth_text()
        ready = self.bluetooth is not None and self.bluetooth.status == "ready"
        searching = ready and self.bluetooth.searching
        items.append(Text(PAD, y + 14, WIDTH - 300, status, 20, "ok" if ready else "error"))
        items.append(Button(WIDTH - PAD - 260, y, 260, ROW - 12, "sucht ..." if searching else "Drucker suchen",
                            self.search if ready and not searching else None, "primary"))
        y += ROW
        found = self.bluetooth.found() if ready else []
        for entry in found:
            self.card(items, y, 76)
            items.append(Text(2 * PAD, y + 10, inner - 250, entry["name"], 22, bold=True))
            state = BLUETOOTH_STATES.get(entry["state"], entry["state"])
            items.append(Text(2 * PAD, y + 42, inner - 250, f"{entry['address']} · {state}", 20,
                              "ok" if entry["state"] == "paired" else "muted"))
            if entry["state"] == "paired":
                items.append(Button(WIDTH - 2 * PAD - 220, y + 12, 220, 52, "Entkoppeln",
                                    lambda entry=entry: self.open(Dialog(f"{entry['name']} entkoppeln?",
                                                                         "Danach druckt er hier nicht mehr, bis er "
                                                                         "wieder gekoppelt ist.", [
                                                                             ("Ja, entkoppeln",
                                                                              lambda: self.unpair(entry), "danger"),
                                                                             ("Nein", None, "normal")])), "danger"))
            elif entry["state"] in ("new", "declined"):
                items.append(Button(WIDTH - 2 * PAD - 220, y + 12, 220, 52, "Koppeln",
                                    lambda entry=entry: self.pair(entry), "primary"))
            y += 76 + PAD
        if ready and not found:
            items.append(Text(PAD, y + 20, WIDTH - 2 * PAD, "Keine Bluetooth-Drucker gefunden: Drucker einschalten, "
                              "dann suchen", 22, "muted", align="center"))
            y += 60
        frame.height = y

    def dialog(self, frame):
        if not self.dialogs:
            return
        dialog = self.dialogs[-1]
        items = frame.overlay
        items.append(Box(0, 0, WIDTH, HEIGHT, "shade"))
        width = 640
        x = (WIDTH - width) // 2
        inner = width - 2 * 20
        title = self.wrap(dialog.title, inner, 24, True)
        text = self.wrap(dialog.text, inner, 20) if dialog.text else []
        choice_row = ROW - 8
        list_height = len(dialog.choices) * choice_row
        top_part = 20 + len(title) * 30 + len(text) * 24 + 12
        shown = max(0, min(list_height, HEIGHT - 40 - top_part - (ROW + 8)))  # the rest scrolls
        height = top_part + shown + ROW + 8
        y = (HEIGHT - height) // 2
        items.append(Box(x, y, width, height, "dialog"))
        cursor = self.paragraph(items, x + 20, y + 18, inner, dialog.title, 24, bold=True, gap=6)
        if dialog.text:
            cursor = self.paragraph(items, x + 20, cursor + 4, inner, dialog.text, 20)
        cursor += 8
        if dialog.choices:
            dialog.scroll = max(0, min(list_height - shown, dialog.scroll))
            frame.choices_area = (x + 20, cursor, inner, shown)
            frame.choices_height, frame.choices_scroll = list_height, dialog.scroll
            for index, (label, action, style) in enumerate(dialog.choices):
                frame.choices.append(Button(0, index * choice_row, inner, ROW - 14, label,
                                            lambda action=action: self.choose(action), style))
        buttons = dialog.buttons
        if buttons:
            width_each = (inner - (len(buttons) - 1) * PAD) // len(buttons)
            for index, (label, action, style) in enumerate(buttons):
                items.append(Button(x + 20 + index * (width_each + PAD), y + height - ROW, width_each, ROW - 16,
                                    label, lambda action=action: self.choose(action), style))

    # ------------------------------------------------------------ dialogs

    def open(self, dialog):
        self.dialogs.append(dialog)

    def choose(self, action):
        """A dialog's button: carry out its action; a Dialog it returns opens next, else the dialog closes."""
        dialog = self.dialogs.pop() if self.dialogs else None
        result = action() if action is not None else None
        if dialog is not None and dialog.question is not None and action is None:
            self.answer(dialog.question, False)
        if isinstance(result, Dialog):
            self.dialogs.append(result)

    def choice_dialog(self, title, choices):
        """A list to choose from, (label, action, chosen) each; a long one opens scrolled to the chosen entry."""
        dialog = Dialog(title, choices=[(("✓ " if chosen else "") + label, action, "normal")
                                        for label, action, chosen in choices],
                        buttons=[("Abbrechen", None, "normal")])
        chosen = [index for index, (_, _, chosen) in enumerate(choices) if chosen]
        if chosen:  # (kept within the list when drawn)
            dialog.scroll = max(0, chosen[0] - 1) * (ROW - 8)
        return dialog

    def media_dialog(self, uid):
        settings = self.settings(uid)
        return self.choice_dialog("Welche Etiketten sind eingelegt?", [
            (medium["name"], lambda medium=medium: self.set_loaded(uid, medium["id"]),
             medium["id"] == settings.get("loaded"))
            for medium in settings.get("media", [])])

    def ribbon_dialog(self, uid):
        settings = self.settings(uid)
        return self.choice_dialog("Welches Farbband ist eingelegt?", [
            (ribbon["name"], lambda ribbon=ribbon: self.set_ribbon(uid, ribbon["id"]),
             ribbon["id"] == settings.get("ribbon"))
            for ribbon in settings.get("ribbons", [])] + [
            ("kein Farbband", lambda: self.set_ribbon(uid, None), settings.get("ribbon") is None)])

    def question_dialog(self, request):
        return Dialog("Bluetooth-Drucker gefunden", f"{request.name} koppeln? Danach druckt er über diesen Agenten.",
                      [("Koppeln", lambda: self.answer(request, True), "primary"),
                       ("Nein", None, "normal")], question=request)

    def answer(self, request, accept):
        with self.lock:
            if request in self.questions:
                self.questions.remove(request)
        (request.accept if accept else request.decline)()
        self.tell("kopple ..." if accept else "nicht gekoppelt")

    # ------------------------------------------------------------ actions

    def refused(self, title, problem):
        """In full: a reason from the server is longer than the note bar (whose "asking ..." goes)."""
        self.tell("", 0)
        self.open(Dialog(title, problem, [("OK", None, "normal")]))

    def show_tab(self, key):
        self.tab, self.detail = key, None
        self.scroll[key] = 0

    def show_printer(self, uid):
        self.detail = uid
        self.scroll[("printer", uid)] = 0

    def back(self):
        self.detail = None

    def pause_all(self):
        if any(self.printers.state(uid)["held"] for uid in self.printers.report()):
            self.printers.resume()
            self.tell("alle fortgesetzt")
        else:
            self.printers.pause()
            self.tell("alle angehalten")

    def abort_all(self):
        """Twice within 5 seconds: the first tap asks on the button itself."""
        if self.clock() < self.confirm_all_until:
            self.confirm_all_until = 0.0
            self.abort(note="alle abgebrochen")
        else:
            self.confirm_all_until = self.clock() + 5

    def search(self):
        self.bluetooth.search()
        self.tell("sucht Bluetooth-Drucker ...")

    def pair(self, entry):
        self.bluetooth.pair(entry["address"])
        self.tell(f"kopple {entry['name']} ...")

    def unpair(self, entry):
        self.bluetooth.unpair(entry["address"])
        self.tell(f"{entry['name']} entkoppelt")

    # ------------------------------------------------------------ touches

    def view_key(self):
        return ("printer", self.detail) if self.tab == "printers" and self.detail is not None else self.tab

    def drag(self, dy):
        """Scroll the content, or a dialog's choices, by a finger moving dy pixels (up: negative)."""
        frame = self.layout()  # the page shown now (it may have changed since it was drawn)
        if self.dialogs:
            if frame.choices_area is not None:
                limit = max(0, frame.choices_height - frame.choices_area[3])
                self.dialogs[-1].scroll = max(0, min(limit, self.dialogs[-1].scroll - dy))
            return
        key = self.view_key()
        visible = CONTENT_BOTTOM - CONTENT_TOP
        limit = max(0, frame.height - visible)
        self.scroll[key] = max(0, min(limit, self.scroll.get(key, 0) - dy))

    def tap(self, x, y):
        """A tap at x, y (screen pixels); returns whether it hit something."""
        self.last_input = self.clock()
        if not self.lit:  # the first touch lights the screen only
            return False
        frame = self.layout()
        if self.dialogs:
            targets = [(item, x, y) for item in frame.overlay]
            if frame.choices_area is not None:
                left, top, width, height = frame.choices_area
                if left <= x < left + width and top <= y < top + height:
                    targets += [(item, x - left, y - top + frame.choices_scroll) for item in frame.choices]
        else:
            offset = self.scroll.get(self.view_key(), 0)
            content = [] if not CONTENT_TOP <= y < CONTENT_BOTTOM else [
                (item, x, y - CONTENT_TOP + offset) for item in frame.content if item.kind == "button"]
            fixed = [(item, x, y) for item in frame.fixed if item.kind == "button"]
            for item, tx, ty in fixed + content:  # the tabs and the note above the content
                if item.hit(tx, ty):
                    item.action()
                    return True
            return False
        for item, tx, ty in reversed(targets):
            if item.kind == "button" and item.hit(tx, ty):
                item.action()
                return True
        return False

    # ------------------------------------------------------------ backlight and loop

    def busy(self):
        reports = self.reports()
        return bool(self.questions or self.alerts(reports) or any(self.printers.jobs(uid) for uid in reports))

    def backlight_on(self):
        return self.busy() or self.clock() - self.last_input < self.backlight_timeout

    def update(self):
        """Before drawing: a pairing question opens its dialog; returns the frame to draw."""
        with self.lock:
            asked = [request for request in self.questions
                     if not any(dialog.question is request for dialog in self.dialogs)]
        for request in asked:
            self.dialogs.append(self.question_dialog(request))
            self.last_input = self.clock()  # light the screen: someone should answer
        return self.layout()

    def run(self, interval=1 / 30, redraw=0.5):
        """Read touches, draw, switch the backlight (in the agent's main thread: SDL wants it so)."""
        drawn, down, moved, last_y = 0.0, None, False, 0
        while True:
            try:
                changed = False
                for event, x, y in self.screen.events():
                    if event == "down":
                        down, moved, last_y = (x, y), False, y
                    elif event == "move" and down is not None:
                        if moved or abs(y - down[1]) > TAP_SLOP or abs(x - down[0]) > TAP_SLOP:
                            moved = True
                            self.drag(y - last_y)
                            last_y = y
                            changed = True
                    elif event == "up" and down is not None:
                        if not moved:
                            self.tap(*down)
                        self.last_input = self.clock()
                        down, changed = None, True
                lit = self.backlight_on()
                if lit != self.lit:
                    self.screen.backlight(lit)
                    self.lit = lit
                if self.lit and (changed or self.clock() - drawn >= redraw):
                    drawn = self.clock()
                    frame = self.update()
                    self.screen.draw(frame, self.scroll.get(self.view_key(), 0))
            except Exception:  # a hiccup of the screen must not stop the agent
                import logging

                logging.getLogger("label_printing.touch").exception("touch screen")
                time.sleep(1)
            time.sleep(interval)

