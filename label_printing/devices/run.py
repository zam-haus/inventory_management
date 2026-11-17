"""Running one print job on a device: check the printer, send, wait until it is printed."""
from __future__ import annotations  # Python 3.9 on older Raspberry Pi OS

import threading
import time
from dataclasses import asdict, dataclass, field

from . import brother, zebra
from .io import DeviceError

PROTOCOLS = {"ptouch": brother, "zpl": zebra}

# Results, see PrintJob.Status: done = the printer reported it printed; sent = it took the data but
# did not confirm (or does not report its status); failed = nothing or not everything was printed.
DONE, SENT, FAILED = "done", "sent", "failed"


@dataclass
class Result:
    status: str
    # Error code (see label_printing.messages), e.g. "paper_out", "wrong_tape", "unreachable".
    code: str = ""
    detail: dict = field(default_factory=dict)
    printer_status: dict | None = None
    # Failed before a single byte reached the printer, so trying again cannot print twice.
    retryable: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{name: data[name] for name in cls.__dataclass_fields__ if name in data})


class Aborted(Exception):
    """The job was aborted (Control.abort) while it was being sent or printed."""


class Control:
    """Pausing and aborting a job from another thread (the print agent's display, the server).

    The job's thread calls steer() between the pages it sends and while it waits for the printer: while
    paused it stops there (a Zebra is also told to pause after the label it is printing, ~PP), and an
    aborted job raises Aborted. A Brother prints what it already got."""

    def __init__(self):
        self.running = threading.Event()
        self.running.set()
        self.aborted = False
        self.by = ""  # who aborted: "display", "server"
        self.sent = 0  # labels (pages) sent so far, for the display

    @property
    def paused(self):
        return not self.running.is_set()

    def pause(self):
        self.running.clear()

    def resume(self):
        self.running.set()

    def abort(self, by=""):
        self.aborted, self.by = True, by
        self.running.set()

    def steer(self, device, pause_command=b"", resume_command=b""):
        """Stop here while paused; the seconds it was paused (to add to the job's timeout). Raises Aborted."""
        if self.aborted:
            raise Aborted
        if not self.paused:
            return 0.0
        started = time.monotonic()
        if pause_command:
            device.write(pause_command)
        self.running.wait()
        if self.aborted:
            raise Aborted
        if resume_command:
            device.write(resume_command)
        return time.monotonic() - started


# How far the label length a Zebra measures may be off the loaded labels' height
LENGTH_TOLERANCE_MM = 2


def status_error(status, expected_tape_mm=None, expected_length=None):
    """The first reason why the printer cannot print now, as (code, detail), or None.
    expected_length: (mm, dpi) of the labels set as loaded in a Zebra, to compare with the length it measured."""
    if status["errors"]:
        return status["errors"][0], {}
    if expected_tape_mm and status.get("media_width_mm") not in (None, expected_tape_mm):
        return "wrong_tape", {"loaded_mm": status["media_width_mm"], "expected_mm": expected_tape_mm}
    if expected_length and status.get("label_length_dots"):
        expected_mm, dpi = expected_length
        measured_mm = round(status["label_length_dots"] * 25.4 / dpi)
        if abs(measured_mm - expected_mm) > LENGTH_TOLERANCE_MM:
            return "wrong_length", {"measured_mm": measured_mm, "expected_mm": expected_mm}
    return None


def query_status(device, language):
    """Only the printer's status, as a Result: done with printer_status, or failed."""
    try:
        with device:
            status = PROTOCOLS[language].query(device)
    except DeviceError as error:
        return Result(FAILED, "unreachable", {"error": str(error)})
    if status is None:
        return Result(FAILED, "no_response")
    return Result(DONE, printer_status=status)


def run_job(device, language, payload, *, expected_tape_mm=None, expected_length=None, pages=1, check_status=True,
            timeout=None, control=None):
    """Print `payload` (printer-ready bytes in `language`) on `device`.

    With check_status, the printer's status is read first (no data is sent if it cannot print, e.g.
    no paper, the wrong tape or labels of another length), and afterwards its notifications until all `pages`
    are printed. The data goes out label by label, so a `control` can pause or abort the job in between."""
    protocol = PROTOCOLS[language]
    control = control or Control()
    timeout = timeout or 20 + 5 * pages
    try:
        device.open()
    except DeviceError as error:
        return Result(FAILED, "unreachable", {"error": str(error)}, retryable=True)
    status = None
    try:
        if check_status:
            status = protocol.query(device)
            if status is None:
                return Result(FAILED, "no_response", retryable=True)
            if error := status_error(status, expected_tape_mm, expected_length):
                return Result(FAILED, error[0], error[1], status)
        try:
            for chunk in protocol.split_pages(payload):
                control.steer(device, protocol.PAUSE, protocol.RESUME)
                device.write(chunk)
                control.sent += 1
        except DeviceError as error:
            return Result(FAILED, "write_failed", {"error": str(error)})
        if not check_status:
            return Result(SENT)
        outcome, last = protocol.wait_until_printed(device, pages, timeout, control=control)
        if outcome == FAILED:
            code, detail = status_error(last) or ("printer_error", {})
            return Result(FAILED, code, detail, last)
        return Result(outcome, "" if outcome == DONE else "no_confirmation", printer_status=last or status)
    except Aborted:
        try:
            protocol.cancel(device)
        except DeviceError:
            pass
        return Result(FAILED, "aborted", {"by": control.by} if control.by else {}, status)
    except DeviceError as error:
        return Result(FAILED, "connection_lost", {"error": str(error)})
    finally:
        device.close()
