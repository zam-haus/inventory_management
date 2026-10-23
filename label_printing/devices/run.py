"""Running one print job on a device: check the printer, send, wait until it is printed."""
from __future__ import annotations  # Python 3.9 on older Raspberry Pi OS

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


def status_error(status, expected_tape_mm=None):
    """The first reason why the printer cannot print now, as (code, detail), or None."""
    if status["errors"]:
        return status["errors"][0], {}
    if expected_tape_mm and status.get("media_width_mm") not in (None, expected_tape_mm):
        return "wrong_tape", {"loaded_mm": status["media_width_mm"], "expected_mm": expected_tape_mm}
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


def run_job(device, language, payload, *, expected_tape_mm=None, pages=1, check_status=True, timeout=None):
    """Print `payload` (printer-ready bytes in `language`) on `device`.

    With check_status, the printer's status is read first (no data is sent if it cannot print, e.g.
    no paper or the wrong tape), and afterwards its notifications until all `pages` are printed."""
    protocol = PROTOCOLS[language]
    timeout = timeout or 20 + 5 * pages
    try:
        device.open()
    except DeviceError as error:
        return Result(FAILED, "unreachable", {"error": str(error)}, retryable=True)
    try:
        if check_status:
            status = protocol.query(device)
            if status is None:
                return Result(FAILED, "no_response", retryable=True)
            if error := status_error(status, expected_tape_mm):
                return Result(FAILED, error[0], error[1], status)
        try:
            device.write(payload)
        except DeviceError as error:
            return Result(FAILED, "write_failed", {"error": str(error)})
        if not check_status:
            return Result(SENT)
        outcome, last = protocol.wait_until_printed(device, pages, timeout)
        if outcome == FAILED:
            code, detail = status_error(last) or ("printer_error", {})
            return Result(FAILED, code, detail, last)
        return Result(outcome, "" if outcome == DONE else "no_confirmation", printer_status=last or status)
    except DeviceError as error:
        return Result(FAILED, "connection_lost", {"error": str(error)})
    finally:
        device.close()
