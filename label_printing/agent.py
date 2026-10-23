"""
Print agent: runs on a computer next to label printers (e.g. a Raspberry Pi, see ops/raspberry-pi/),
finds USB printers by itself and serves one or more inventories at the same time.

    python3 -m label_printing.agent [--config /etc/label-agent/config.json]

With each inventory it registers once with its own ID and a token it makes up, then waits until an
admin activates it. It reports the printers it finds (they appear in the admin, inactive until
activated and named) and their status (errors, loaded tape and its colours, label length), fetches
the jobs of its active printers, prints them and reports how they went.

The configuration (JSON, see ops/raspberry-pi/label-agent/config.json):
    {"servers": ["https://inventar.zam.haus"],
     "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
     "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}

Needs only Python 3.9+ and label_printing/devices; no Django, no database.
"""
import argparse
import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .devices import usb, zebra
from .devices.io import DeviceError, device_for
from .devices.run import FAILED, Result, query_status, run_job

VERSION = "2"
CONFIG_PATHS = ("/boot/label-agent/config.json", "/boot/firmware/label-agent/config.json",
                "/etc/label-agent/config.json")
DEFAULTS = {"servers": [], "state_dir": None, "poll_interval": 2, "status_interval": 30,
            "scan_interval": 10, "report_interval": 60, "static_printers": []}
log = logging.getLogger("label_printing.agent")


def default_state_dir():
    """Where the agent keeps its ID and tokens: the service's state directory (systemd StateDirectory=,
    /var/lib/label-agent), else ~/.local/state/label-agent, e.g. when trying it out on a laptop."""
    if os.environ.get("STATE_DIRECTORY"):
        return os.environ["STATE_DIRECTORY"].split(":")[0]
    return os.path.join(os.path.expanduser("~"), ".local", "state", "label-agent")


def machine_uid():
    """A stable ID of this computer, not revealing its machine-id."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as file:
                machine = file.read().strip()
        except OSError:
            continue
        if machine:
            return "agent-" + hashlib.sha256(("label-agent:" + machine).encode()).hexdigest()[:20]
    return None


class State:
    """What the agent keeps: its ID and one token per server (state_dir/state.json, readable by it only)."""

    def __init__(self, directory):
        self.path = os.path.join(directory, "state.json")
        self.lock = threading.Lock()
        try:
            with open(self.path) as file:
                self.data = json.load(file)
        except (OSError, ValueError):
            self.data = {}
        if not self.data.get("uid"):
            self.data["uid"] = machine_uid() or "agent-" + secrets.token_hex(10)
            self.save()

    @property
    def uid(self):
        return self.data["uid"]

    def token(self, server):
        with self.lock:
            tokens = self.data.setdefault("tokens", {})
            if server not in tokens:
                tokens[server] = secrets.token_urlsafe(32)
                self.save()
            return tokens[server]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"
        with open(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
            json.dump(self.data, file, indent=1)
        os.replace(temporary, self.path)


class Printers:
    """The printers this computer reaches: USB printers found by usb.find_printers and configured static
    ones. Every access to a device holds its lock, so jobs of two servers never mix."""

    def __init__(self, static=(), find=usb.find_printers):
        self.static = {entry["uid"]: dict(entry) for entry in static}
        self.find = find
        self.found = {}
        self.statuses = {}
        self.locks = {}
        self.identify_tried = {}
        self.lock = threading.Lock()

    def device_lock(self, uid):
        with self.lock:
            return self.locks.setdefault(uid, threading.Lock())

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
        """Read every printer's status (skipping printers that are printing)."""
        with self.lock:
            printers = list(self.found.values())
        for printer in printers:
            lock = self.device_lock(printer["uid"])
            if not lock.acquire(blocking=False):
                continue
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects turn POST requests into GET; the agent follows them by itself instead."""

    def redirect_request(self, *args, **kwargs):
        return None


class Unauthorized(Exception):
    pass


class Link(threading.Thread):
    """One inventory: registration, polling, jobs."""

    def __init__(self, server, state, printers, config, hostname):
        super().__init__(name=f"link {server}", daemon=True)
        self.server = server.rstrip("/")
        self.base = self.server
        self.state, self.printers, self.config, self.hostname = state, printers, config, hostname
        self.opener = urllib.request.build_opener(NoRedirect)
        self.registered = False
        self.active = None
        self.last_report, self.last_full_report = None, 0.0

    def request(self, path, data, token=True, redirects=3):
        """POST JSON; (status code, decoded JSON or None). Follows redirects to another address."""
        headers = {"Content-Type": "application/json", "User-Agent": f"label-printing-agent/{VERSION}"}
        if token:
            headers["Authorization"] = f"Bearer {self.state.token(self.server)}"
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
                    return self.request(path, data, token, redirects - 1)
            if error.code == 401 and token:
                raise Unauthorized from error
            try:
                return error.code, json.loads(error.read() or b"null")
            except ValueError:
                return error.code, None

    def register(self):
        status, answer = self.request("register", {"uid": self.state.uid, "token": self.state.token(self.server),
                                                   "hostname": self.hostname, "version": VERSION}, token=False)
        if status in (200, 201):
            self.registered = True
            log.info("%s: registered as %s%s", self.server, (answer or {}).get("name", self.state.uid),
                     "" if (answer or {}).get("active") else ", waiting to be activated in the admin")
            return True
        log.warning("%s: registration refused (%s): %s", self.server, status, (answer or {}).get("error", ""))
        return False

    def printer_reports(self):
        """All printers with their status when something changed, else once every report_interval."""
        report = self.printers.report()
        now = time.monotonic()
        if report == self.last_report and now - self.last_full_report < self.config["report_interval"]:
            return {}
        self.last_report, self.last_full_report = report, now
        return report

    def poll_once(self):
        """Report, fetch one job and print it; True if there was a job."""
        if not self.registered and not self.register():
            raise ConnectionError("not registered")
        status, answer = self.request("poll", {"version": VERSION, "hostname": self.hostname,
                                               "printers": self.printer_reports()})
        if status != 200 or answer is None:
            self.last_report = None  # send everything again next time
            raise ConnectionError(f"poll answered {status}")
        if answer.get("active") != self.active:
            self.active = answer.get("active")
            log.info("%s: %s", self.server, "active" if self.active else "waiting to be activated in the admin")
        job = answer.get("job")
        if not job:
            return False
        self.print(job)
        return True

    def print(self, job):
        printer = self.printers.get(job["printer"])
        if printer is None:
            outcome = Result(FAILED, "unreachable", {"error": f"printer {job['printer']} is not connected"})
        else:
            payload = base64.b64decode(job["payload"])
            log.info("%s: job %s, %d bytes for %s", self.server, job["id"], len(payload), job["printer"])
            with self.printers.device_lock(job["printer"]):
                outcome = run_job(device_for(printer["device"]), job["language"], payload,
                                  expected_tape_mm=job.get("expected_tape_mm"), pages=job.get("pages", 1),
                                  check_status=job.get("check_status", True))
            self.printers.remember(job["printer"], outcome.printer_status)
        log.info("%s: job %s %s %s", self.server, job["id"], outcome.status, outcome.code)
        self.request(f"jobs/{job['id']}/result", outcome.to_dict())

    def run(self):
        interval = self.config["poll_interval"]
        backoff = interval
        while True:
            try:
                if not self.poll_once():
                    time.sleep(interval)
                backoff = interval
            except Unauthorized:
                log.warning("%s: token not known (agent deleted?); registering again", self.server)
                self.registered = False
                time.sleep(5)
            except (OSError, ValueError, ConnectionError) as error:  # URLError is an OSError
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help=f"JSON file (default: the first of {', '.join(CONFIG_PATHS)})")
    parser.add_argument("--server", action="append", default=[], help="inventory address (adds to the configuration)")
    parser.add_argument("--state-dir", help="where the agent keeps its ID and tokens "
                                            "(default: the service's state directory, else ~/.local/state/label-agent)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    servers = list(dict.fromkeys(config["servers"] + args.server))
    if not servers:
        parser.error("no server: give --server or set servers in the configuration")
    for printer in config["static_printers"]:
        device_for(printer["device"])  # validates
    state_dir = args.state_dir or config["state_dir"] or default_state_dir()
    try:
        state = State(state_dir)
    except OSError as error:
        parser.error(f"cannot keep the agent's state in {state_dir} ({error.strerror}); give --state-dir")
    printers = Printers(config["static_printers"])
    hostname = socket.gethostname()
    log.info("print agent %s (%s) on %s for %s", VERSION, state.uid, hostname, ", ".join(servers))
    threading.Thread(target=monitor, args=(printers, config), name="monitor", daemon=True).start()
    links = [Link(server, state, printers, config, hostname) for server in servers]
    for link in links:
        link.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
