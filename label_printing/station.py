"""
What the print agent's touch screen (touch.py) shows and does, apart from how it looks: the printers' and the
server's state in words, the network, and the actions (pause, go on, abort, labels and ribbon loaded in a Zebra,
test and calibration labels), run so that the display stays responsive. Plain Python, no Django; the texts are
German, like the people standing at the printers.
"""
import base64
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
        # Jobs shown on their page, by id: {"loading": True} until the server answered, then {"job", "labels"
        # (each with "png": the preview's PNG), "problem", "more"}, or {"problem"} if it did not
        self.job_details = {}

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
            tapes = self.settings(uid).get("tapes") or []
            return text + (f" ({', '.join(tapes)})" if tapes else "")
        settings = self.settings(uid)
        medium = next((medium for medium in settings.get("media", []) if medium["id"] == settings.get("loaded")), None)
        if settings.get("language") != "zpl":
            return medium["name"] if medium else ""
        # a Zebra: the labels set as loaded, and next to them the ribbon set as loaded
        ribbon = next((entry["name"] for entry in settings.get("ribbons", []) if entry["id"] == settings.get("ribbon")),
                      "kein Farbband gesetzt" if settings.get("thermal_transfer", True) else "")
        return " · ".join(part for part in (medium["name"] if medium else "", ribbon) if part)

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
        if report.get("missing"):
            return "✗ nicht gefunden (Kabel, Strom, Bluetooth?)"
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

    def printer_names(self, uids, reports=None):
        """Printers that would each do: "P-touch Werkstatt oder Brother PT-P700"."""
        reports = reports or {}
        return " oder ".join(self.printer_name(uid, reports.get(uid)) for uid in uids)

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
            steps = []
            if entry.get("loaded"):
                steps.append(f"{entry['loaded']} herausnehmen")
            if entry.get("material"):
                steps.append(f"{entry['material']} einlegen")
            if entry.get("ribbon_out"):
                steps.append(f"Farbband {entry['ribbon_out']} herausnehmen")
            if entry.get("ribbon_in"):
                steps.append(f"Farbband {entry['ribbon_in']} einlegen")
            steps.append(f"{count} Auftr{'äge' if count != 1 else 'ag'} warten")
            text = ". ".join(steps) + "."
            zebra = bool(entry.get("medium")) and self.settings(uid).get("language") == "zpl"
            ribbon_only = not entry.get("material") and entry.get("ribbon_in")
            found.append(Alert(("waiting", uid, entry.get("medium")), "ribbon" if ribbon_only else "waiting", uid,
                               self.printer_names(entry.get("printers") or [uid], reports), text,
                               medium=entry["medium"] if zebra else None, material=entry.get("material", "")))
        asked = {alert.uid for alert in found if alert.kind == "ribbon"}
        for uid, settings in link.settings.items():
            if settings.get("ribbon_problem") and uid in reports and uid not in asked:
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
            if not link.set_loaded(uid, medium):
                self.tell("✗ nicht gespeichert")
            elif problem := link.settings.get(uid, {}).get("ribbon_problem"):
                self.ribbon_needed(uid, problem)
            else:
                self.tell("gespeichert")
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

    def ribbon_needed(self, uid, problem):
        """New labels set as loaded that the ribbon in the printer does not suit: another ribbon is to be put in."""
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

    def report_with_expected(self, reports):
        """The printers found here, and those the server expects here (active there) but not found since the
        agent started (unplugged, switched off, a Bluetooth printer away): {uid: report}, those with "missing"."""
        link = self.link
        expected = {uid: {"missing": True} for uid, settings in (link.settings.items() if link else ())
                    if settings.get("active") and uid not in reports}
        return {**reports, **expected}

    def cancel_job(self, uid, job_id):
        """Abort one job of a printer here (being printed or waiting in it), in the background."""
        def run():
            self.printers.abort(uid, job_id=job_id)
            self.tell(f"#{job_id} abgebrochen")
        self.background(run)

    def cancel_offered(self, job_id):
        """Cancel a waiting job one of the printers here could print (on the server)."""
        link = self.link

        def run():
            problem = link.cancel_job(job_id)
            self.tell(f"✗ {problem}" if problem else f"#{job_id} abgebrochen", 5 if problem else 3)
        self.tell("breche ab ...", 10)
        self.background(run)

    def extend_offered(self, job_id):
        """Let a waiting job wait longer (its countdown tapped)."""
        link = self.link

        def run():
            problem = link.extend_job(job_id)
            self.tell(f"✗ {problem}" if problem else f"#{job_id} wartet länger", 5 if problem else 3)
        self.background(run)

    def load_job(self, job_id):
        """A job with previews of its labels (job_details), from the server in the background."""
        link = self.link
        with self.lock:
            self.job_details[job_id] = {"loading": True}

        def run():
            answer, problem = link.job_detail(job_id) if link is not None else (None, "nicht verbunden")
            if answer is None:
                entry = {"problem": problem}
            else:
                labels = []
                for label in answer.get("labels") or []:
                    try:
                        labels.append({**label, "png": base64.b64decode(label.get("image") or "")})
                    except ValueError:
                        continue
                entry = {"job": answer.get("job") or {}, "labels": labels, "problem": answer.get("problem") or "",
                         "more": answer.get("more") or 0}
            with self.lock:
                self.job_details = {**{key: value for key, value in self.job_details.items()
                                       if key == job_id or len(self.job_details) < 8}, job_id: entry}
        self.background(run)

    def reprint(self, job_id):
        """Print a job again (on the server: services.again), in the background."""
        link = self.link

        def run():
            new, problem = link.reprint_job(job_id) if link is not None else (None, "nicht verbunden")
            if problem:
                self.refused(f"#{job_id} nicht nochmal gedruckt", problem)
            else:
                self.tell(f"nochmal aufgegeben als #{new}", 5)
        self.tell("gibt nochmal auf ...", 10)
        self.background(run)

    def cut(self, uid):
        """Brother: feed and cut, in the background (the printer's cutter button, from here)."""
        def run():
            outcome = self.printers.cut(uid)
            if outcome.status == "failed":
                self.tell("✗ " + ("erst die Aufträge abwarten" if outcome.code == "printing" else
                                  ERRORS.get(outcome.code, outcome.code or "nicht abgeschnitten")), 5)
            else:
                self.tell("abgeschnitten")
        self.tell("schneide ab ...", 10)
        self.background(run)

    def set_offsets(self, uid, offset_x, offset_y):
        """The printer's calibration in dots, saved on the server in the background."""
        link = self.link

        def run():
            problem = link.set_offsets(uid, offset_x, offset_y)
            self.tell(f"✗ {problem}" if problem else "Versatz gespeichert", 5 if problem else 3)
        self.background(run)

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
