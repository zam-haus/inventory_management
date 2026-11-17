"""
What the print agent's touch screen (touch.py) shows and does, apart from how it looks: the printers' and the
server's state in words, the network, and the actions (pause, go on, abort, labels and ribbon loaded in a Zebra,
test and calibration labels), run so that the display stays responsive. Plain Python, no Django; the texts are
German, like the people standing at the printers.
"""
import logging
import subprocess
import threading
import time
from urllib.parse import urlsplit

log = logging.getLogger("label_printing.station")

ERRORS = {
    "no_media": "keine Kassette", "end_of_media": "Band zu Ende", "cutter_jam": "Schneide klemmt",
    "weak_batteries": "Akku schwach", "high_voltage_adapter": "falsches Netzteil", "wrong_media": "falsches Band",
    "communication_error": "Übertragungsfehler", "cover_open": "Deckel offen", "overheating": "zu heiß, warten",
    "paper_out": "keine Etiketten", "paused": "Pause am Drucker", "head_open": "Druckkopf offen",
    "ribbon_out": "Farbband leer", "temperature": "Kopftemperatur", "buffer_full": "Speicher voll",
    "system_error": "Systemfehler", "unreachable": "nicht erreichbar", "no_response": "antwortet nicht",
}


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


class Alert:
    """Something that needs someone at a printer (Station.alerts): kind "waiting" (labels to load; medium: the labels'
    id if they are for a Zebra, to confirm them loaded) or "ribbon" (a Zebra's ribbon does not suit its labels)."""

    def __init__(self, key, kind, uid, name, text, medium=None, material=""):
        self.key, self.kind, self.uid, self.name, self.text = key, kind, uid, name, text
        self.medium, self.material = medium, material


OWN_LABELS = {"test": "Testetikett", "calibration": "Kalibrieretikett"}


class Station:
    """What the display shows and does (see the module's docstring), for the one server the agent works for: the
    configured server first, another one chosen on the display (connection: agent.Connection)."""

    held_text = "⏸ angehalten"

    def __init__(self, hostname, clock=time.monotonic, addresses=addresses):
        self.hostname, self.clock = hostname, clock
        self.find_addresses, self.addresses, self.addresses_at = addresses, [], None
        self.printers, self.connection, self.bluetooth = None, None, None
        self.questions = []  # pairing requests (devices.bluetooth.PairRequest), shown until answered
        self.note, self.note_until = "", 0.0
        self.lock = threading.Lock()

    def attach(self, printers, connection, bluetooth=None):
        self.printers, self.connection, self.bluetooth = printers, connection, bluetooth

    @property
    def link(self):
        """The link to the server now (the connection replaces it when another server is chosen), or None."""
        return self.connection.link if self.connection is not None else None

    def settings(self, uid):
        """The server's view of a printer (name, active, language; a Zebra's media and ribbons), {} while it does not
        know it."""
        link = self.link
        return link.settings.get(uid, {}) if link is not None else {}

    @staticmethod
    def server_name(server):
        return urlsplit(server).hostname or server

    def ask(self, request):
        """A pairing request of devices.bluetooth (from its thread): shown until answered."""
        with self.lock:
            self.questions.append(request)

    def tell(self, text, seconds=3):
        with self.lock:
            self.note, self.note_until = text, self.clock() + seconds

    def printer_name(self, uid, report=None):
        if self.settings(uid).get("name"):
            return self.settings(uid)["name"]
        info = (report or {}).get("info") or {}
        return info.get("product") or info.get("model") or uid

    def loaded_text(self, uid, status):
        if status.get("media_width_mm"):
            text = f"{status['media_width_mm']} mm"
            if status.get("text_color") and status.get("tape_color"):
                text += f" {status['text_color']} auf {status['tape_color']}"
            return text
        settings = self.settings(uid)
        medium = next((medium for medium in settings.get("media", []) if medium["id"] == settings.get("loaded")), None)
        return medium["name"] if medium else ""

    def printer_text(self, uid, report):
        state = self.printers.state(uid)
        status = report.get("status") or {}
        settings = self.settings(uid)
        if state["printing"]:
            pages = state["printing"].get("pages", 1)
            text = ("⏸ pausiert" if state["paused"] else "▶ druckt") + f", {pages} Etikett{'en' if pages != 1 else ''}"
            return text + (f", {state['queued']} weitere" if state["queued"] else "")
        if state["held"]:
            return self.held_text
        if status.get("errors"):
            return "✗ " + ERRORS.get(status["errors"][0], status["errors"][0])
        if settings.get("ribbon_problem"):
            return "✗ Farbband passt nicht zu den Etiketten"
        if not settings:
            return "neu, wird gemeldet"
        if not settings.get("active"):
            return "inaktiv: im Admin aktivieren"
        loaded = self.loaded_text(uid, status)
        return "✓ bereit" + (f", {loaded}" if loaded else "")

    def alerts(self, reports):
        """What needs someone at the printers: labels waiting for a printer that has other labels loaded (or none
        left), and a Zebra whose ribbon does not suit its labels."""
        link = self.link
        if link is None:
            return []
        found = []
        for entry in link.waiting:
            uid = entry.get("printer")
            count = entry.get("jobs", 1)
            text = (f"{entry.get('material', '?')} einlegen: {count} Auftr{'äge' if count != 1 else 'ag'} warten."
                    + (f" {entry['reason']}" if entry.get("reason") else ""))
            if entry.get("ribbon_problem"):
                text += f" Achtung: {entry['ribbon_problem']}"
            zebra = bool(entry.get("medium")) and self.settings(uid).get("language") == "zpl"
            found.append(Alert(("waiting", uid, entry.get("medium")), "waiting", uid,
                               self.printer_name(uid, reports.get(uid)), text,
                               medium=entry["medium"] if zebra else None, material=entry.get("material", "")))
        for uid, settings in link.settings.items():
            if settings.get("ribbon_problem") and uid in reports:
                found.append(Alert(("ribbon", uid), "ribbon", uid, self.printer_name(uid, reports[uid]),
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

    def set_ribbon(self, uid, ribbon):
        link = self.link

        def run():
            if not link.set_ribbon(uid, ribbon):
                self.tell("✗ nicht gespeichert")
            elif link.settings.get(uid, {}).get("ribbon_problem"):
                self.tell("gespeichert, passt aber nicht!", 5)
            else:
                self.tell("gespeichert")
        self.background(run)
        self.tell("speichere ...", 10)

    def set_loaded(self, uid, medium):
        """Tell the server in the background: the display stays responsive."""
        link = self.link

        def run():
            self.tell("gespeichert" if link.set_loaded(uid, medium) else "✗ nicht gespeichert")
        self.background(run)
        self.tell("speichere ...", 10)

    def print_own_label(self, uid, label):
        """Ask the server for the printer's test or calibration label, in the background."""
        link = self.link

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
        """(label, which) of the test and calibration label, if the printer is active on the server."""
        return list((label, which) for which, label in OWN_LABELS.items()) if self.settings(uid).get("active") else []

    def switch_server(self, index):
        """Work for another configured server from now on (until the agent starts again): everything is asked of
        it anew, as after a reboot; not while a printer has jobs of the server now."""
        if not self.connection.switch(index):
            self.tell("✗ erst die Aufträge abwarten oder abbrechen", 5)
            return
        self.tell(f"verbinde mit {self.server_name(self.connection.servers[index]['url'])} ...", 5)

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
