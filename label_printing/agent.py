"""
Print agent: runs on a computer next to label printers (e.g. a Raspberry Pi, see ops/raspberry-pi/),
finds USB printers by itself and serves one or more inventories at the same time.

    python3 -m label_printing.agent [--config /etc/label-agent/config.json]

An admin creates the agent in each inventory (admin → Label printing → Print agents) and gives it its
token, which goes into the configuration next to the inventory's address. The agent reports the printers
it finds (new ones appear in the admin, inactive until checked, named and activated) and their status
(errors, loaded tape and its colours, label length), fetches the jobs of its active printers, prints them
and reports how they went.

The configuration (JSON, see ops/raspberry-pi/config.json):
    {"servers": [{"url": "https://inventar.zam.haus", "token": "…"}],
     "poll_interval": 2, "status_interval": 30, "scan_interval": 10,
     "static_printers": [{"uid": "zebra-lan", "device": "tcp://192.0.2.10:9100", "language": "zpl"}]}

Needs only Python 3.9+ and label_printing/devices; no Django, no database.
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

from .devices import usb, zebra
from .devices.io import DeviceError, device_for
from .devices.run import FAILED, Result, query_status, run_job

VERSION = "4"
CONFIG_PATHS = ("/boot/label-agent/config.json", "/boot/firmware/label-agent/config.json",
                "/etc/label-agent/config.json")
DEFAULTS = {"servers": [], "poll_interval": 2, "status_interval": 30,
            "scan_interval": 10, "report_interval": 60, "static_printers": []}
log = logging.getLogger("label_printing.agent")


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


class Refused(Exception):
    """The server does not let the agent in: unknown token (401) or the agent is deactivated (403)."""


class Link(threading.Thread):
    """One inventory: polling, jobs."""

    def __init__(self, server, printers, config, hostname):
        super().__init__(name=f"link {server['url']}", daemon=True)
        self.server = server["url"].rstrip("/")
        self.token = server["token"]
        self.base = self.server
        self.printers, self.config, self.hostname = printers, config, hostname
        self.opener = urllib.request.build_opener(NoRedirect)
        self.last_report, self.last_full_report = None, 0.0

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
        """Report, fetch one job and print it; True if there was a job."""
        status, answer = self.request("poll", {"version": VERSION, "hostname": self.hostname,
                                               "printers": self.printer_reports()})
        if status != 200 or answer is None:
            self.last_report = None  # send everything again next time
            raise ConnectionError(f"poll answered {status}")
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
                                  expected_tape_mm=job.get("expected_tape_mm"),
                                  expected_length=job.get("expected_length"), pages=job.get("pages", 1),
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
            except Refused as error:
                log.warning("%s: %s; next try in 60 s", self.server, error)
                time.sleep(60)
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
    printers = Printers(config["static_printers"])
    hostname = socket.gethostname()
    log.info("print agent %s on %s for %s", VERSION, hostname, ", ".join(server["url"] for server in servers))
    threading.Thread(target=monitor, args=(printers, config), name="monitor", daemon=True).start()
    links = [Link(server, printers, config, hostname) for server in servers]
    for link in links:
        link.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
