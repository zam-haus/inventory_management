"""
The print agent's display (PiFace Control & Display, devices/piface.py): two lines of 16 characters and
eight switches. Plain Python, no Django; the texts are German, like the people standing at the printers.

Pages, one after another with the navigation switch (left/right, or the buttons 2 and 3):
* labels waiting for a printer that has other labels loaded ("! Zebra Lager": which labels, how many jobs, what
  is loaded); they come first, and the display jumps to a new one. On a Zebra, pressing the navigation switch
  sets those labels as loaded, once they are in;
* an overview: the address in the network, servers connected, printers, printing; then all addresses
  (Netzwerk) and whether Bluetooth works, else why not;
* each server: connected, or why not;
* a Zebra whose ribbon does not suit its labels (by material: wax, wax/resin, resin): it comes first, and the backlight
  blinks until another ribbon is set (pressing the navigation switch: the ribbons to choose from);
* each printer: printing (paused), held, its error, inactive in the admin, or ready with what is loaded. Pressing
  the navigation switch opens its menu: pause or go on, abort, the labels and the ribbon loaded in a Zebra.

Questions (pairing a Bluetooth printer that was found) take the display until answered: navigation switch
pressed = yes, button 1 (left) = no.

The navigation switch is at the top right, the buttons below the display, from the left: 1 back (closes a menu, else back to the first page), 2 and 3 previous
and next page, 4 pauses all printers (again: go on), 5 aborts all jobs (press twice within 5 seconds).
"""
import logging
import subprocess
import threading
import time
from urllib.parse import urlsplit

from .devices.piface import LEFT, PRESS, RIGHT

BACK, PREVIOUS, NEXT, PAUSE_ALL, ABORT_ALL = 0, 1, 2, 3, 4
log = logging.getLogger("label_printing.panel")
WIDTH = 16

ERRORS = {
    "no_media": "keine Kassette", "end_of_media": "Band zu Ende", "cutter_jam": "Schneide klemmt",
    "weak_batteries": "Akku schwach", "high_voltage_adapter": "falsches Netzteil", "wrong_media": "falsches Band",
    "communication_error": "Übertragungsfehler", "cover_open": "Deckel offen", "overheating": "zu heiß, warten",
    "paper_out": "keine Etiketten", "paused": "Pause am Drucker", "head_open": "Druckkopf offen",
    "ribbon_out": "Farbband leer", "temperature": "Kopftemperatur", "buffer_full": "Speicher voll",
    "system_error": "Systemfehler", "unreachable": "nicht erreichbar", "no_response": "antwortet nicht",
}


def scroll(text, offset):
    """A window of 16 characters on a long text, `offset` steps after it was first shown: it stands for a
    moment, then runs."""
    if len(text) <= WIDTH:
        return text
    loop = text + "   "
    position = max(0, offset - 6) % len(loop)
    return (loop + loop)[position:position + WIDTH]


BLUETOOTH = {
    "starting": "startet ...", "ready": "✓ sucht Drucker", "no_library": "✗ Pakete fehlen (python3-dbus, python3-gi)",
    "no_bluez": "✗ kein Zugriff auf BlueZ", "no_adapter": "✗ kein Bluetooth-Adapter",
}


def addresses():
    """The computer's addresses in the network, IPv4 first: [(interface, address)] (iproute2's ip)."""
    try:
        output = subprocess.run(["ip", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True,
                                timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in output.splitlines():
        fields = line.split()  # "3: wlan0    inet 192.168.1.23/24 brd … scope global dynamic wlan0 …"
        if len(fields) > 3 and fields[2] in ("inet", "inet6"):
            found.append((fields[2] != "inet", fields[1], fields[3].split("/")[0]))
    return [(interface, address) for _ipv6, interface, address in sorted(found, key=lambda entry: entry[0])]


def ago(seconds):
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 3600)} h"


class Page:
    def __init__(self, key, title, text, action=None, alert=False, urgent=False):
        self.key, self.title, self.text, self.action, self.alert = key, title, text, action, alert or urgent
        self.urgent = urgent  # the backlight blinks while it is there


class Alert:
    """Something that needs someone at a printer (Station.alerts): kind "waiting" (labels to load; medium: the labels'
    id if they are for a Zebra, to confirm them loaded) or "ribbon" (a Zebra's ribbon does not suit its labels)."""

    def __init__(self, key, kind, link, uid, name, text, medium=None, material=""):
        self.key, self.kind, self.link, self.uid, self.name, self.text = key, kind, link, uid, name, text
        self.medium, self.material = medium, material


class Menu:
    """A list to choose from: the title above, the entry below; an entry's action returns a Menu to open,
    Menu.BACK, or None (done: all menus close)."""
    BACK = "back"

    def __init__(self, title, entries):
        self.title, self.entries, self.index = title, entries, 0


OWN_LABELS = {"test": "Testetikett", "calibration": "Kalibrieretikett"}


class Station:
    """What a display of the print agent shows and does, whatever it looks like (the PiFace Control & Display here,
    the touch screen in touch.py): the printers' and servers' state in words, the network, and the actions (pause,
    go on, abort, labels and ribbon loaded in a Zebra, test and calibration labels), run so that the display stays
    responsive."""

    held_text = "⏸ angehalten"

    def __init__(self, hostname, clock=time.monotonic, addresses=addresses):
        self.hostname, self.clock = hostname, clock
        self.find_addresses, self.addresses, self.addresses_at = addresses, [], None
        self.printers, self.links, self.bluetooth = None, [], None
        self.questions = []  # pairing requests (devices.bluetooth.PairRequest), shown until answered
        self.note, self.note_until = "", 0.0
        self.lock = threading.Lock()

    def attach(self, printers, links, bluetooth=None):
        self.printers, self.links, self.bluetooth = printers, links, bluetooth

    def ask(self, request):
        """A pairing request of devices.bluetooth (from its thread): shown until answered."""
        with self.lock:
            self.questions.append(request)

    def tell(self, text, seconds=3):
        with self.lock:
            self.note, self.note_until = text, self.clock() + seconds

    def printer_name(self, uid, report=None):
        for link in self.links:
            if link.settings.get(uid, {}).get("name"):
                return link.settings[uid]["name"]
        info = (report or {}).get("info") or {}
        return info.get("product") or info.get("model") or uid

    def loaded_text(self, uid, status):
        if status.get("media_width_mm"):
            text = f"{status['media_width_mm']} mm"
            if status.get("text_color") and status.get("tape_color"):
                text += f" {status['text_color']} auf {status['tape_color']}"
            return text
        for link in self.links:
            settings = link.settings.get(uid, {})
            medium = next((medium for medium in settings.get("media", []) if medium["id"] == settings.get("loaded")),
                          None)
            if medium:
                return medium["name"]
        return ""

    def printer_text(self, uid, report):
        state = self.printers.state(uid)
        status = report.get("status") or {}
        settings = [link.settings[uid] for link in self.links if uid in link.settings]
        if state["printing"]:
            pages = state["printing"].get("pages", 1)
            text = ("⏸ pausiert" if state["paused"] else "▶ druckt") + f", {pages} Etikett{'en' if pages != 1 else ''}"
            return text + (f", {state['queued']} weitere" if state["queued"] else "")
        if state["held"]:
            return self.held_text
        if status.get("errors"):
            return "✗ " + ERRORS.get(status["errors"][0], status["errors"][0])
        if any(entry.get("ribbon_problem") for entry in settings):
            return "✗ Farbband passt nicht zu den Etiketten"
        if not settings:
            return "neu, wird gemeldet"
        if not any(entry.get("active") for entry in settings):
            return "inaktiv: im Admin aktivieren"
        loaded = self.loaded_text(uid, status)
        return "✓ bereit" + (f", {loaded}" if loaded else "")

    def alerts(self, reports):
        """What needs someone at the printers, in the order of the servers: labels waiting for a printer that has
        other labels loaded (or none left), and a Zebra whose ribbon does not suit its labels."""
        found = []
        for link in self.links:
            for entry in link.waiting:
                uid = entry.get("printer")
                count = entry.get("jobs", 1)
                text = (f"{entry.get('material', '?')} einlegen: {count} Auftr{'äge' if count != 1 else 'ag'} warten."
                        + (f" {entry['reason']}" if entry.get("reason") else ""))
                if entry.get("ribbon_problem"):
                    text += f" Achtung: {entry['ribbon_problem']}"
                zebra = bool(entry.get("medium")) and link.settings.get(uid, {}).get("language") == "zpl"
                found.append(Alert(("waiting", link.server, uid, entry.get("medium")), "waiting", link, uid,
                                   self.printer_name(uid, reports.get(uid)), text,
                                   medium=entry["medium"] if zebra else None, material=entry.get("material", "")))
            for uid, settings in link.settings.items():
                if settings.get("ribbon_problem") and uid in reports:
                    found.append(Alert(("ribbon", link.server, uid), "ribbon", link, uid,
                                       self.printer_name(uid, reports[uid]),
                                       "Farbband passt nicht! " + settings["ribbon_problem"]))
        return found

    def network(self):
        """The addresses, asked again every 15 seconds (DHCP, WLAN changing)."""
        if self.addresses_at is None or self.clock() - self.addresses_at > 15:
            self.addresses, self.addresses_at = self.find_addresses(), self.clock()
        return self.addresses

    def link_text(self, link):
        state = link.state
        since = ago(self.clock() - state["since"])
        if state["code"] == "ok":
            return "✓ verbunden"
        if state["code"] == "connecting":
            return "verbinde ..."
        if state["code"] == "refused":
            if "unknown token" in state["message"]:
                return "✗ Token unbekannt (Admin)"
            if "deactivated" in state["message"]:
                return "✗ Agent im Admin deaktiviert"
            return "✗ abgelehnt: " + state["message"]
        if state["code"] == "error":
            return f"✗ Serverfehler seit {since}: {state['message']}"
        return f"✗ nicht erreichbar seit {since}"

    def set_ribbon(self, link, uid, ribbon):
        def run():
            if not link.set_ribbon(uid, ribbon):
                self.tell("✗ nicht gespeichert")
            elif link.settings.get(uid, {}).get("ribbon_problem"):
                self.tell("gespeichert, passt aber nicht!", 5)
            else:
                self.tell("gespeichert")
        self.background(run)
        self.tell("speichere ...", 10)

    def set_loaded(self, link, uid, medium):
        """Tell the server in the background: the display stays responsive."""
        def run():
            self.tell("gespeichert" if link.set_loaded(uid, medium) else "✗ nicht gespeichert")
        self.background(run)
        self.tell("speichere ...", 10)

    def print_own_label(self, link, uid, label):
        """Ask the server for the printer's test or calibration label, in the background."""
        def run():
            if problem := link.print_own_label(uid, label):
                self.refused(f"{OWN_LABELS[label]} nicht gedruckt", problem)
            else:
                self.tell(f"{OWN_LABELS[label]} kommt")
        self.tell("fordere an ...", 10)
        self.background(run)

    def refused(self, title, problem):
        self.tell(f"✗ {problem}", 8)

    def own_label_entries(self, uid):
        """(label, link, which) for each server the printer is active on."""
        active = [link for link in self.links if link.settings.get(uid, {}).get("active")]
        return [(OWN_LABELS[which] + (f" ({urlsplit(link.server).hostname})" if len(active) > 1 else ""), link, which)
                for link in active for which in OWN_LABELS]

    def do(self, action, uid, note):
        action(uid)
        self.tell(note)

    def abort(self, uid=None, note="abgebrochen"):
        """In the background: aborted jobs are reported to the server, which may take long when it is unreachable;
        the display goes on meanwhile."""
        def run():
            self.printers.abort(uid)
            self.tell(note)
        self.background(run)

    @staticmethod
    def background(work):
        threading.Thread(target=work, daemon=True).start()


class Panel(Station):
    """The PiFace Control & Display: pages and menus on two lines of 16 characters (see the module's docstring)."""

    def __init__(self, display, hostname, backlight_timeout=600, clock=time.monotonic, addresses=addresses):
        super().__init__(hostname, clock=clock, addresses=addresses)
        self.display, self.backlight_timeout = display, backlight_timeout
        self.menus = []
        self.page_key, self.shown_since = None, clock()
        self.abort_until = 0.0
        self.alerts_seen = set()
        self.last_input = clock()
        self.lit = None

    held_text = "⏸ angehalten (Menü: fortsetzen)"

    # ------------------------------------------------------------ pages

    def pages(self):
        reports = self.printers.report() if self.printers else {}
        pages = []
        for alert in self.alerts(reports):
            if alert.kind == "waiting":
                action = (self.confirm_loaded(alert.link, alert.uid, alert.medium, alert.material)
                          if alert.medium else None)
                pages.append(Page(alert.key, "! " + alert.name, alert.text, action, alert=True))
            else:
                pages.append(Page(alert.key, "! " + alert.name, alert.text + " (OK: Farbband wählen)",
                                  lambda alert=alert: self.ribbon_menu(alert.link, alert.uid), urgent=True))
        connected = sum(link.state["code"] == "ok" for link in self.links)
        printing = sum(1 for uid in reports if self.printers.state(uid)["printing"])
        network = self.network()
        summary = (network[0][1] if network else "kein Netz") + f", Server {connected}/{len(self.links)}, "
        summary += f"{len(reports)} Drucker"
        summary += f", {printing} druck{'en' if printing != 1 else 't'}" if printing else ""
        pages.append(Page("overview", self.hostname, summary))
        pages.append(Page("network", "Netzwerk", ", ".join(f"{interface} {address}" for interface, address in network)
                          or "keine Adresse (Kabel, WLAN?)"))
        if self.bluetooth is None:
            pages.append(Page("bluetooth", "Bluetooth", "aus (config.json)"))
        else:
            text = BLUETOOTH.get(self.bluetooth.status, self.bluetooth.status)
            pages.append(Page("bluetooth", "Bluetooth", text + (f": {self.bluetooth.problem}"
                                                                if self.bluetooth.problem else "")))
        for link in self.links:
            pages.append(Page(("server", link.server), urlsplit(link.server).hostname or link.server,
                              self.link_text(link)))
        for uid, report in sorted(reports.items(), key=lambda item: self.printer_name(*item).lower()):
            pages.append(Page(("printer", uid), self.printer_name(uid, report), self.printer_text(uid, report),
                              lambda uid=uid: self.printer_menu(uid)))
        if not reports:
            pages.append(Page("none", "Keine Drucker", "USB- oder Bluetooth-Drucker anschließen"))
        return pages

    # ------------------------------------------------------------ menus

    def printer_menu(self, uid):
        state = self.printers.state(uid)
        entries = []
        if state["held"] or state["paused"]:
            entries.append(("Fortsetzen", lambda: self.do(self.printers.resume, uid, note="fortgesetzt")))
        elif state["printing"] or state["queued"]:
            entries.append(("Pausieren", lambda: self.do(self.printers.pause, uid, note="angehalten")))
        else:
            entries.append(("Anhalten", lambda: self.do(self.printers.pause, uid, note="angehalten")))
        if state["printing"] or state["queued"]:
            entries.append(("Abbrechen", lambda: Menu("Wirklich abbrechen?", [
                ("Ja, abbrechen", lambda: self.abort(uid)),
                ("Nein", lambda: Menu.BACK)])))
        for link in self.links:
            settings = link.settings.get(uid, {})
            server = f" ({urlsplit(link.server).hostname})" if len(self.links) > 1 else ""
            if settings.get("language") == "zpl" and settings.get("active") and settings.get("media"):
                entries.append(("Etiketten eingelegt" + server,
                                lambda link=link, settings=settings: self.media_menu(link, uid, settings)))
            if settings.get("language") == "zpl" and settings.get("active") and settings.get("ribbons"):
                entries.append(("Farbband eingelegt" + server, lambda link=link: self.ribbon_menu(link, uid)))
        entries += [(label, lambda link=link, which=which: self.print_own_label(link, uid, which))
                    for label, link, which in self.own_label_entries(uid)]
        entries.append(("Zurück", lambda: Menu.BACK))
        return Menu(self.printer_name(uid), entries)

    def media_menu(self, link, uid, settings):
        return Menu("Eingelegt:", [
            (("✓ " if medium["id"] == settings.get("loaded") else "") + medium["name"],
             lambda medium=medium: self.set_loaded(link, uid, medium["id"]))
            for medium in settings["media"]] + [("Zurück", lambda: Menu.BACK)])

    def ribbon_menu(self, link, uid):
        settings = link.settings.get(uid, {})
        return Menu("Farbband:", [
            (("✓ " if ribbon["id"] == settings.get("ribbon") else "") + ribbon["name"],
             lambda ribbon=ribbon: self.set_ribbon(link, uid, ribbon["id"]))
            for ribbon in settings.get("ribbons", [])] + [
            (("✓ " if settings.get("ribbon") is None else "") + "kein Farbband", lambda: self.set_ribbon(link, uid, None)),
            ("Zurück", lambda: Menu.BACK)])

    def confirm_loaded(self, link, uid, medium, material):
        return lambda: Menu(f"{material} drin?", [
            ("Ja, ist drin", lambda: self.set_loaded(link, uid, medium)),
            ("Nein", lambda: Menu.BACK)])

    # ------------------------------------------------------------ buttons

    def press(self, switch):
        self.last_input = self.shown_since = self.clock()  # what comes up runs from its start
        if switch in (LEFT, PREVIOUS):
            switch = LEFT
        elif switch in (RIGHT, NEXT):
            switch = RIGHT
        with self.lock:
            question = self.questions[0] if self.questions else None
        if question is not None:
            if switch in (PRESS, BACK):
                with self.lock:
                    self.questions.pop(0)
                (question.accept if switch == PRESS else question.decline)()
                self.tell("kopple ..." if switch == PRESS else "nicht gekoppelt")
            return
        if switch == PAUSE_ALL:
            if any(self.printers.state(uid)["held"] for uid in self.printers.report()):
                self.printers.resume()
                self.tell("alle fortgesetzt")
            else:
                self.printers.pause()
                self.tell("alle angehalten")
            return
        if switch == ABORT_ALL:
            if self.clock() < self.abort_until:
                self.abort_until = 0.0
                self.abort(note="alle abgebrochen")
            else:
                self.abort_until = self.clock() + 5
                self.tell("Alle abbrechen? Taste 5 nochmal", 5)
            return
        if self.menus:
            menu = self.menus[-1]
            if switch == BACK:
                self.menus.pop()
            elif switch in (LEFT, RIGHT):
                menu.index = (menu.index + (1 if switch == RIGHT else -1)) % len(menu.entries)
            elif switch == PRESS:
                result = menu.entries[menu.index][1]()
                if isinstance(result, Menu):
                    self.menus.append(result)
                elif result == Menu.BACK:
                    self.menus.pop()
                else:
                    self.menus = []
            return
        pages = self.pages()
        index = self.index_of(pages)
        if switch == BACK:
            self.show_page(pages[0])
        elif switch in (LEFT, RIGHT):
            self.show_page(pages[(index + (1 if switch == RIGHT else -1)) % len(pages)])
        elif switch == PRESS and pages[index].action:
            result = pages[index].action()
            if isinstance(result, Menu):
                self.menus.append(result)

    def index_of(self, pages):
        return next((i for i, page in enumerate(pages) if page.key == self.page_key), 0)

    def show_page(self, page):
        if page.key != self.page_key:
            self.page_key, self.shown_since = page.key, self.clock()

    # ------------------------------------------------------------ drawing

    def lines(self):
        """The two lines to show now."""
        now = self.clock()
        offset = int((now - self.shown_since) / 0.35)
        with self.lock:
            question = self.questions[0] if self.questions else None
            note = self.note if now < self.note_until else ""
        if question is not None:
            return ["Koppeln? OK/Nein", scroll(question.name, offset)]
        if note and not self.menus:
            return [self.page_title(), scroll(note, offset)]
        if self.menus:
            menu = self.menus[-1]
            title = menu.title if not note else note
            return [scroll(title, offset), scroll(f"{menu.index + 1}/{len(menu.entries)} "
                                                  f"{menu.entries[menu.index][0]}", offset)]
        pages = self.pages()
        new = [page for page in pages if page.alert and page.key not in self.alerts_seen]
        self.alerts_seen = {page.key for page in pages if page.alert}
        if new:  # a new alert: show it, and light the display
            self.show_page(new[0])
            self.last_input = now
        page = pages[self.index_of(pages)]
        self.show_page(page)
        return [scroll(page.title, offset), scroll(page.text, offset)]

    def page_title(self):
        pages = self.pages()
        return pages[self.index_of(pages)].title[:WIDTH]

    def backlight_on(self):
        """On while there is something to see or the buttons were used lately; blinking while something urgent
        (a ribbon that does not suit the labels) is there."""
        if any(page.urgent for page in self.pages()):
            return int(self.clock() / 0.7) % 2 == 0
        busy = self.questions or self.alerts_seen or (
            self.printers and any(self.printers.state(uid)["printing"] for uid in self.printers.report()))
        return bool(busy) or self.clock() - self.last_input < self.backlight_timeout

    def run(self, interval=0.05, redraw=0.35):
        previous, stable, drawn = set(), set(), 0.0
        while True:
            try:
                switches = self.display.switches()
                if switches == previous:  # the same twice in a row: no bouncing
                    for switch in sorted(switches - stable):
                        self.press(switch)
                    stable = switches
                previous = switches
                if self.clock() - drawn >= redraw:
                    drawn = self.clock()
                    self.display.show(self.lines())
                    lit = self.backlight_on()
                    if lit != self.lit:
                        self.display.backlight(lit)
                        self.lit = lit
            except Exception:  # a display hiccup must not stop the agent
                log.exception("display")
                time.sleep(1)
            time.sleep(interval)
