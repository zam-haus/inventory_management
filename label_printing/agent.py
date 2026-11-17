"""
Print agent: runs on a computer next to label printers (e.g. a Raspberry Pi, see ops/raspberry-pi/),
finds USB and Bluetooth printers by itself and serves one or more inventories at the same time.

    python3 -m label_printing.agent [--config /etc/label-agent/config.json]

An admin creates the agent in each inventory (admin → Label printing → Print agents) and gives it its
token, which goes into the configuration next to the inventory's address. The agent reports the printers
it finds (new ones appear in the admin, inactive until checked, named and activated) and their status
(errors, loaded tape and its colours, label length), fetches the jobs of its active printers, prints them
(each printer on its own, so several print at the same time) and reports how they went. Jobs can be paused
and aborted, on the display or in the admin.

With a touch screen (label_printing/touch.py, e.g. the Raspberry Pi Touch Display) or a PiFace Control & Display
(label_printing/panel.py) it shows the jobs, the connections to the servers, the printers, the labels waiting
for a printer that has other labels loaded, and a Zebra whose ribbon does not suit its labels; there a Zebra's
labels and ribbon can be set as loaded, Bluetooth printers paired (on the touch screen also searched for and
unpaired) and jobs paused or aborted.

The configuration (JSON, see ops/raspberry-pi/config.json):
    {"servers": [{"url": "https://inventar.zam.haus", "token": "…"}],
     "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
     "display": "auto", "screen_rotation": 0, "bluetooth": true, "bluetooth_pairing": "confirm",
     "read_only": true,
     "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}

Needs Python 3.9+ and label_printing/devices, no Django; the touch screen needs python3-pygame, the PiFace display
python3-spidev, Bluetooth python3-dbus and python3-gi (without them the agent runs without). "read_only" is for
ops/raspberry-pi/update.sh: the Pi's system read-only, to spare the SD card.
"""
import argparse
import base64
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .devices import usb, zebra
from .devices.io import DeviceError, device_for
from .devices.run import FAILED, Control, Result, query_status, run_job

VERSION = "5.2"
CONFIG_PATHS = ("/boot/label-agent/config.json", "/boot/firmware/label-agent/config.json",
                "/etc/label-agent/config.json")
DEFAULTS = {"servers": [], "poll_interval": 2, "status_interval": 30,
            "scan_interval": 10, "report_interval": 60, "static_printers": [],
            # "auto": a touch screen if there is one, else a PiFace Control & Display if there is one; "touch",
            # "piface": that one; "none". screen_rotation 180: a touch screen mounted upside down
            "display": "auto", "backlight_timeout": 600, "screen_rotation": 0,
            # Pairing: "confirm" on the display (without display: by itself), or "auto" always by itself
            "bluetooth": True, "bluetooth_pairing": "confirm", "bluetooth_scan_interval": 60,
            "bluetooth_pin": "0000", "bluetooth_channel": 1,
            # for ops/raspberry-pi/update.sh: the Pi's system read-only (raspi-config's overlay file system)
            "read_only": False}
log = logging.getLogger("label_printing.agent")


class Task:
    """A job of one server on its way to the printer, with the control to pause or abort it."""

    def __init__(self, link, job):
        self.link, self.job, self.control = link, job, Control()

    @property
    def id(self):
        return self.job["id"]


class Spooler(threading.Thread):
    """Prints the jobs of one printer one after another (the printers print at the same time). Held (paused
    on the display or in the admin), it pauses the job being printed and starts no other."""

    def __init__(self, printers, uid):
        super().__init__(name=f"printer {uid}", daemon=True)
        self.printers, self.uid = printers, uid
        self.condition = threading.Condition()
        self.queued, self.current, self.held = [], None, False

    def submit(self, task):
        with self.condition:
            if self.held:
                task.control.pause()
            self.queued.append(task)
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                while not self.queued or self.held:
                    self.condition.wait()
                task = self.current = self.queued.pop(0)
            try:
                outcome = self.printers.print_task(self.uid, task)
            except Exception as error:  # a broken printer must not stop the spooler
                log.exception("%s: job %s", self.uid, task.id)
                outcome = Result(FAILED, "printer_error", {"error": str(error)})
            try:
                task.link.report(task.job, outcome)
            finally:  # busy until reported: the next poll must not see the job still held and the printer free
                with self.condition:
                    self.current = None

    @property
    def busy(self):
        with self.condition:
            return bool(self.current or self.queued or self.held)

    def state(self):
        """What the display shows: {"printing": job or None, "paused": bool, "held": bool, "queued": n}."""
        with self.condition:
            current = self.current
            return {"printing": current.job if current else None, "server": current.link.server if current else "",
                    "paused": bool(current and current.control.paused), "held": self.held,
                    "queued": len(self.queued)}

    def jobs(self):
        """The jobs here for the display, the one being printed first: [{"id", "server", "pages", "sent", "subject",
        "printing", "paused"}]."""
        with self.condition:
            tasks = ([self.current] if self.current else []) + self.queued
            return [{"id": task.id, "server": task.link.server, "pages": task.job.get("pages", 1),
                     "sent": task.control.sent if task is self.current else 0,
                     "subject": task.job.get("subject", ""), "printing": task is self.current,
                     "paused": task.control.paused or self.held} for task in tasks]

    def tasks(self, link):
        """{job id: {"printer", "paused"}} of the link's jobs here, so the server keeps them (lease)."""
        with self.condition:
            tasks = ([self.current] if self.current else []) + self.queued
            return {str(task.id): {"printer": self.uid, "paused": task.control.paused or self.held}
                    for task in tasks if task.link is link}

    def pause(self):
        with self.condition:
            self.held = True
            for task in ([self.current] if self.current else []) + self.queued:
                task.control.pause()

    def resume(self):
        with self.condition:
            self.held = False
            for task in ([self.current] if self.current else []) + self.queued:
                task.control.resume()
            self.condition.notify()

    def abort(self, by, job_id=None, link=None):
        """Abort the job being printed and those waiting here (or only the job `job_id` of `link`)."""
        with self.condition:
            dropped = [task for task in self.queued if job_id is None or (task.id, task.link) == (job_id, link)]
            self.queued = [task for task in self.queued if task not in dropped]
            current = self.current
            if current and (job_id is None or (current.id, current.link) == (job_id, link)):
                current.control.abort(by)
        for task in dropped:
            task.link.report(task.job, Result(FAILED, "aborted", {"by": by}))

    def command(self, link, job_id, command):
        """A command of the server for one of its jobs here: "pause", "resume" or "abort"."""
        with self.condition:
            tasks = ([self.current] if self.current else []) + self.queued
            task = next((task for task in tasks if (task.id, task.link) == (job_id, link)), None)
            if task is None:
                return False
            paused = task.control.paused or self.held
        if command == "abort":
            self.abort("server", job_id, link)
        elif command == "pause" and not paused:
            self.pause()
        elif command == "resume" and paused:
            self.resume()
        return True


class Printers:
    """The printers this computer reaches: USB and Bluetooth printers found by `find` and configured static
    ones. Every access to a device holds its lock, so jobs of two servers never mix; each printer prints its
    jobs in a spooler of its own."""

    def __init__(self, static=(), find=usb.find_printers):
        self.static = {entry["uid"]: dict(entry) for entry in static}
        self.find = find
        self.found = {}
        self.statuses = {}
        self.locks = {}
        self.spoolers = {}
        self.identify_tried = {}
        self.lock = threading.Lock()

    def device_lock(self, uid):
        with self.lock:
            return self.locks.setdefault(uid, threading.Lock())

    def spooler(self, uid):
        with self.lock:
            if uid not in self.spoolers:
                self.spoolers[uid] = Spooler(self, uid)
                self.spoolers[uid].start()
            return self.spoolers[uid]

    def all_spoolers(self):
        with self.lock:
            return list(self.spoolers.values())
    def scan(self):
        found = {printer["uid"]: printer for printer in self.find()}
        found.update(self.static)
        with self.lock:
            known = dict(self.found)
        new = [uid for uid in found if uid not in known]
        gone = [uid for uid in known if uid not in found]
        for uid in found:
            # Keep what was identified before; ask new printers, and again after a while if they did not answer
            # (outside self.lock: identify locks the device).
            printer = {**known[uid], **found[uid]} if uid in known else found[uid]
            if self.needs_identification(printer):
                self.identify_tried[uid] = time.monotonic()
                printer = {**printer, **self.identify(printer)}
            found[uid] = printer
        with self.lock:
            self.found = found
        for uid in new:
            log.info("printer found: %s (%s, %s)", uid, found[uid].get("product") or found[uid]["language"],
                     found[uid]["device"])
        for uid in gone:
            log.info("printer gone: %s", uid)
            self.statuses.pop(uid, None)

    def needs_identification(self, printer, retry_after=300):
        if printer.get("language") != "zpl" or printer.get("dpi"):
            return False
        tried = self.identify_tried.get(printer["uid"])
        return tried is None or time.monotonic() - tried > retry_after

    def identify(self, printer):
        """What a Zebra says about itself (model, resolution); Brother models are known by their USB ID."""
        try:
            with self.device_lock(printer["uid"]), device_for(printer["device"]) as device:
                return zebra.identify(device) or {}
        except (DeviceError, OSError) as error:
            log.warning("%s: no identification (%s)", printer["uid"], error)
            return {}

    def check(self):
        """Read every printer's status, all at once (a Bluetooth printer that is off takes a while to fail),
        skipping printers that are printing."""
        with self.lock:
            printers = list(self.found.values())
        if printers:
            with ThreadPoolExecutor(max_workers=len(printers)) as pool:
                list(pool.map(self.check_one, printers))

    def check_one(self, printer):
        lock = self.device_lock(printer["uid"])
        if not lock.acquire(blocking=False):
            return
        try:
            result = query_status(device_for(printer["device"]), printer["language"])
        finally:
            lock.release()
        self.statuses[printer["uid"]] = result.printer_status or {"ok": False, "errors": [result.code]}

    def report(self):
        """{uid: {"device", "info", "status"}} for the servers."""
        with self.lock:
            printers = dict(self.found)
        return {uid: {"device": printer["device"], "status": self.statuses.get(uid),
                      "info": {key: value for key, value in printer.items() if key not in ("uid", "device")}}
                for uid, printer in printers.items()}

    def get(self, uid):
        with self.lock:
            return self.found.get(uid)

    def remember(self, uid, status):
        if status:
            self.statuses[uid] = status

    # ------------------------------------------------------------ jobs

    def submit(self, task):
        self.spooler(task.job["printer"]).submit(task)

    def print_task(self, uid, task):
        """Print a task on its printer (in the printer's spooler) and keep the status it reported."""
        printer = self.get(uid)
        job = task.job
        if printer is None:
            return Result(FAILED, "unreachable", {"error": f"printer {uid} is not connected"})
        if task.control.aborted:
            return Result(FAILED, "aborted", {"by": task.control.by})
        payload = base64.b64decode(job["payload"])
        log.info("%s: job %s, %d bytes for %s", task.link.server, job["id"], len(payload), uid)
        with self.device_lock(uid):
            outcome = run_job(device_for(printer["device"]), job["language"], payload,
                              expected_tape_mm=job.get("expected_tape_mm"),
                              expected_length=job.get("expected_length"), pages=job.get("pages", 1),
                              check_status=job.get("check_status", True), control=task.control)
        self.remember(uid, outcome.printer_status)
        return outcome

    def busy(self):
        """The printers that print, have jobs waiting or are held: no new jobs for them."""
        return sorted(spooler.uid for spooler in self.all_spoolers() if spooler.busy)

    def held(self):
        """The printers held (on the display or by a paused job): the server shows it and can let them go on."""
        return sorted(spooler.uid for spooler in self.all_spoolers() if spooler.held)

    def tasks_of(self, link):
        tasks = {}
        for spooler in self.all_spoolers():
            tasks.update(spooler.tasks(link))
        return tasks

    def command(self, link, job_id, command):
        return any(spooler.command(link, job_id, command) for spooler in self.all_spoolers())

    def jobs(self, uid):
        """The jobs of a printer here, the one being printed first (Spooler.jobs)."""
        with self.lock:
            spooler = self.spoolers.get(uid)
        return spooler.jobs() if spooler else []

    def state(self, uid):
        with self.lock:
            spooler = self.spoolers.get(uid)
        return spooler.state() if spooler else {"printing": None, "server": "", "paused": False, "held": False,
                                                "queued": 0}

    def pause(self, uid=None):
        """Hold a printer (or all, also those that have not printed yet): the job being printed pauses, no other
        starts."""
        for each in [uid] if uid else sorted(set(self.report()) | {spooler.uid for spooler in self.all_spoolers()}):
            self.spooler(each).pause()

    def resume(self, uid=None):
        for spooler in self.all_spoolers():
            if uid is None or spooler.uid == uid:
                spooler.resume()

    def abort(self, uid=None, by="display"):
        """Abort the jobs of a printer (or all printers): the one being printed and those waiting."""
        for spooler in self.all_spoolers():
            if uid is None or spooler.uid == uid:
                spooler.abort(by)

    def wait_idle(self, timeout=30):
        """Until no printer prints or has jobs waiting (tests)."""
        deadline = time.monotonic() + timeout
        while any(spooler.busy and not spooler.held for spooler in self.all_spoolers()):
            if time.monotonic() > deadline:
                raise TimeoutError("printers still busy")
            time.sleep(0.02)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects turn POST requests into GET; the agent follows them by itself instead."""

    def redirect_request(self, *args, **kwargs):
        return None


class ServerError(Exception):
    """The server answered, but not as expected (e.g. 404 without label printing, 500)."""


class Refused(Exception):
    """The server does not let the agent in: unknown token (401) or the agent is deactivated (403)."""


class Link(threading.Thread):
    """One inventory: polling, jobs, results. What the display shows of it: state, settings, waiting."""

    def __init__(self, server, printers, config, hostname):
        super().__init__(name=f"link {server['url']}", daemon=True)
        self.server = server["url"].rstrip("/")
        self.token = server["token"]
        self.base = self.server
        self.printers, self.config, self.hostname = printers, config, hostname
        self.opener = urllib.request.build_opener(NoRedirect)
        self.last_report, self.last_full_report = None, 0.0
        # "connecting", "ok", "offline" (not reached), "refused" (token, deactivated), "error" (other answers)
        self.state = {"code": "connecting", "message": "", "since": time.monotonic()}
        # The server's view of the agent's printers: {uid: {"name", "active", "language", "media", "loaded"}}
        self.settings = {}
        # Labels waiting for one of the agent's printers to get other labels: [{"printer", "material", …}]
        self.waiting = []

    def request(self, path, data, redirects=3):
        """POST JSON; (status code, decoded JSON or None). Follows redirects to another address."""
        headers = {"Content-Type": "application/json", "User-Agent": f"label-printing-agent/{VERSION}",
                   "Authorization": f"Bearer {self.token}"}
        request = urllib.request.Request(f"{self.base}/print/api/agent/{path}", data=json.dumps(data).encode(),
                                         headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308) and redirects and error.headers.get("Location"):
                target = urllib.parse.urljoin(request.full_url, error.headers["Location"])
                new_base = target.split("/print/api/agent/")[0]
                if new_base != self.base:
                    log.warning("%s redirects to %s; using that address", self.base, new_base)
                    self.base = new_base
                    return self.request(path, data, redirects - 1)
            try:
                answer = json.loads(error.read() or b"null")
            except ValueError:
                answer = None
            if error.code in (401, 403):
                raise Refused((answer or {}).get("error") or f"refused ({error.code})") from error
            return error.code, answer

    def printer_reports(self):
        """All printers with their status when something changed, else once every report_interval."""
        report = self.printers.report()
        now = time.monotonic()
        if report == self.last_report and now - self.last_full_report < self.config["report_interval"]:
            return {}
        self.last_report, self.last_full_report = report, now
        return report

    def poll_once(self):
        """Report the printers, take the server's commands and new jobs (one for each printer that is free);
        True if there were jobs."""
        status, answer = self.request("poll", {"version": VERSION, "hostname": self.hostname,
                                               "printers": self.printer_reports(), "busy": self.printers.busy(),
                                               "held": self.printers.held(), "printing": self.printers.tasks_of(self)})
        if status != 200 or answer is None:
            self.last_report = None  # send everything again next time
            raise ServerError(f"poll answered {status}")
        self.settings = answer.get("printers") or {}
        self.waiting = answer.get("waiting") or []
        for job_id, command in (answer.get("commands") or {}).items():
            if self.printers.command(self, int(job_id), command):
                log.info("%s: job %s: %s (from the server)", self.server, job_id, command)
        for uid, command in (answer.get("printer_commands") or {}).items():
            if command == "resume":  # held on the display or by a paused job, perhaps aborted since
                self.printers.resume(uid)
                log.info("%s: printer %s goes on (from the server)", self.server, uid)
        jobs = answer.get("jobs") or ([answer["job"]] if answer.get("job") else [])  # "job": servers before 5
        for job in jobs:
            self.printers.submit(Task(self, job))
        self.mark("ok")
        return bool(jobs)

    def report(self, job, outcome, attempts=3):
        """Tell the server how a job went (from the printer's spooler); tried again a few times, as a lost result
        would count a printed label as failed."""
        log.info("%s: job %s %s %s", self.server, job["id"], outcome.status, outcome.code)
        for attempt in range(attempts):
            try:
                self.request(f"jobs/{job['id']}/result", outcome.to_dict())
                return
            except (OSError, ValueError, Refused) as error:
                log.warning("%s: result of job %s not reported: %s", self.server, job["id"], error)
                time.sleep(5 * (attempt + 1))

    def set_loaded(self, uid, medium):
        """Set the labels loaded in a Zebra (confirmed on the display); True if the server took it."""
        try:
            status, answer = self.request("printers/loaded", {"printer": uid, "medium": medium})
        except (OSError, ValueError, Refused) as error:
            log.warning("%s: labels of %s not set: %s", self.server, uid, error)
            return False
        if status != 200:
            log.warning("%s: labels of %s not set: %s", self.server, uid, (answer or {}).get("error", status))
            return False
        if uid in self.settings:
            self.settings[uid] = {**self.settings[uid], "loaded": medium}
        self.waiting = [entry for entry in self.waiting if entry.get("printer") != uid]
        log.info("%s: labels %s set as loaded in %s", self.server, medium, uid)
        return True

    def set_ribbon(self, uid, ribbon):
        """Set the ribbon loaded in a Zebra (None: none), confirmed on the display; True if the server took it."""
        try:
            status, answer = self.request("printers/ribbon", {"printer": uid, "ribbon": ribbon})
        except (OSError, ValueError, Refused) as error:
            log.warning("%s: ribbon of %s not set: %s", self.server, uid, error)
            return False
        if status != 200:
            log.warning("%s: ribbon of %s not set: %s", self.server, uid, (answer or {}).get("error", status))
            return False
        if uid in self.settings:
            self.settings[uid] = {**self.settings[uid], "ribbon": ribbon,
                                  "ribbon_problem": (answer or {}).get("ribbon_problem", "")}
        log.info("%s: ribbon %s set as loaded in %s", self.server, ribbon, uid)
        return True

    def mark(self, code, message=""):
        if code != self.state["code"] or message != self.state["message"]:
            self.state = {"code": code, "message": message, "since": time.monotonic()}

    def run(self):
        interval = self.config["poll_interval"]
        backoff = interval
        while True:
            try:
                if not self.poll_once():
                    time.sleep(interval)
                backoff = interval
            except Refused as error:
                self.mark("refused", str(error))
                log.warning("%s: %s; next try in 60 s", self.server, error)
                time.sleep(60)
            except (OSError, ValueError, ServerError) as error:  # URLError is an OSError
                self.mark("error" if isinstance(error, ServerError) else "offline", str(error))
                backoff = min(backoff * 2, 60)
                log.warning("%s: %s; next try in %d s", self.server, error, backoff)
                time.sleep(backoff)


def monitor(printers, config):
    """Find printers every scan_interval and read their status every status_interval."""
    checked = 0.0
    while True:
        try:
            printers.scan()
            if time.monotonic() - checked >= config["status_interval"]:
                printers.check()
                checked = time.monotonic()
        except Exception:  # keep watching; a broken printer must not stop the agent
            log.exception("checking printers failed")
        time.sleep(config["scan_interval"])


def load_config(path=None):
    paths = [path] if path else [candidate for candidate in CONFIG_PATHS if os.path.exists(candidate)][:1]
    config = dict(DEFAULTS)
    for candidate in paths:
        with open(candidate) as file:
            config.update(json.load(file))
        log.info("configuration: %s", candidate)
    return config


def servers_of(config, urls=(), tokens=()):
    """[{"url", "token"}]: the configuration's servers and those given on the command line, each once."""
    if len(urls) != len(tokens):
        raise ValueError("give a --token for each --server")
    servers = {}
    for entry in list(config["servers"]) + [{"url": url, "token": token} for url, token in zip(urls, tokens)]:
        if not isinstance(entry, dict) or not entry.get("url") or not entry.get("token"):
            raise ValueError(f"a server needs its url and the agent's token from the admin: {entry!r}")
        servers[entry["url"].rstrip("/")] = {"url": entry["url"].rstrip("/"), "token": entry["token"]}
    return list(servers.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help=f"JSON file (default: the first of {', '.join(CONFIG_PATHS)})")
    parser.add_argument("--server", action="append", default=[], help="inventory address (adds to the configuration)")
    parser.add_argument("--token", action="append", default=[],
                        help="the agent's token from that inventory's admin, one per --server")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    try:
        servers = servers_of(config, args.server, args.token)
    except ValueError as error:
        parser.error(str(error))
    if not servers:
        parser.error("no server: give --server and --token or set servers in the configuration")
    for printer in config["static_printers"]:
        device_for(printer["device"])  # validates
    hostname = socket.gethostname()
    log.info("print agent %s on %s for %s", VERSION, hostname, ", ".join(server["url"] for server in servers))
    panel = open_display(config, hostname)
    bluetooth = start_bluetooth(config, panel)
    printers = Printers(config["static_printers"],
                        find=(lambda: usb.find_printers() + bluetooth.printers()) if bluetooth else usb.find_printers)
    threading.Thread(target=monitor, args=(printers, config), name="monitor", daemon=True).start()
    links = [Link(server, printers, config, hostname) for server in servers]
    for link in links:
        link.start()
    if panel is not None:
        panel.attach(printers, links, bluetooth)
    try:
        if panel is not None and getattr(panel, "screen", None) is not None:
            panel.run()  # the touch screen: SDL wants its events and drawing in the thread that opened it
        else:
            if panel is not None:
                threading.Thread(target=panel.run, name="panel", daemon=True).start()
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass


def open_display(config, hostname):
    """What runs the display (touch.Touch for a touch screen, panel.Panel for a PiFace Control & Display), or None
    (none configured, or none there)."""
    kind = config["display"]
    if kind in ("auto", "touch"):
        from .devices.screen import NoScreen, TouchScreen

        try:
            screen = TouchScreen(rotation=config["screen_rotation"])
        except NoScreen as error:
            (log.error if kind == "touch" else log.info)("no touch screen: %s", error)
        else:
            from .touch import Touch

            return Touch(screen, hostname, backlight_timeout=config["backlight_timeout"], version=VERSION)
    if kind in ("auto", "piface"):
        from .devices.piface import NoDisplay, PiFaceCAD

        try:
            display = PiFaceCAD()
        except NoDisplay as error:
            (log.error if kind == "piface" else log.info)("no PiFace display: %s", error)
        else:
            log.info("PiFace Control & Display found")
            from .panel import Panel

            return Panel(display, hostname, backlight_timeout=config["backlight_timeout"])
    return None


def keep_pairings():
    """Bluetooth pairings changed: have them saved on the boot partition, so they survive a reboot of a Pi whose
    system is read-only (ops/raspberry-pi/label-agent-keep.path does it as root; the agent may not read them)."""
    folder = os.environ.get("RUNTIME_DIRECTORY")  # systemd: RuntimeDirectory=label-agent
    if not folder:
        return
    with open(os.path.join(folder.split(":")[0], "keep-bluetooth"), "w") as file:
        file.write(str(time.time()))


def start_bluetooth(config, panel):
    """Bluetooth printers, if Bluetooth is on in the configuration (else None); if it cannot start, its status
    says why (the display shows it) and it finds nothing. Pairing is confirmed on the display, if there is one
    and bluetooth_pairing is "confirm"."""
    if not config["bluetooth"]:
        return None
    from .devices.bluetooth import Bluetooth

    ask = panel.ask if panel is not None and config["bluetooth_pairing"] == "confirm" else None
    bluetooth = Bluetooth(scan_interval=config["bluetooth_scan_interval"], channel=config["bluetooth_channel"],
                          pin=str(config["bluetooth_pin"]), ask=ask, on_change=keep_pairings)
    bluetooth.start()
    return bluetooth


if __name__ == "__main__":
    main()
