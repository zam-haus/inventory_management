"""
Brother P-touch status (raster command reference of PT-E550W/P750W and PT-P900 series, "Status information").

The printer answers ESC i S with 32 bytes, and sends the same 32-byte record unasked when a
page is printed, an error occurs or the phase changes.
"""
import time

from . import snmp

STATUS_SIZE = 32
# Network printers report the status record over SNMP (they do not answer ESC i S on port 9100).
STATUS_OID = "1.3.6.1.4.1.2435.3.3.9.1.6.1.0"
# Invalidate (clears a half-received job), initialize, then ask for the status.
STATUS_REQUEST = b"\x00" * 100 + b"\x1b@" + b"\x1biS"

# Error information 1 (byte 8) and 2 (byte 9).
ERRORS_1 = {
    0x01: "no_media",
    0x02: "end_of_media",
    0x04: "cutter_jam",
    0x08: "weak_batteries",
    0x40: "high_voltage_adapter",
}
ERRORS_2 = {
    0x01: "wrong_media",
    0x02: "buffer_full",
    0x04: "communication_error",
    0x08: "buffer_full",
    0x10: "cover_open",
    0x20: "overheating",
    0x80: "system_error",
}
MEDIA_TYPES = {
    0x00: "none",
    0x01: "laminated",
    0x03: "non_laminated",
    0x04: "fabric",
    0x11: "heat_shrink",
    0x13: "fle",
    0x14: "flexible_id",
    0x15: "satin",
    0x17: "heat_shrink_3_1",
    0xFF: "incompatible",
}
# Tape colour (byte 24) and text colour (byte 25), named like Brother's German tape list (label stock).
TAPE_COLORS = {
    0x01: "weiß", 0x02: "andere", 0x03: "transparent", 0x04: "rot", 0x05: "blau", 0x06: "gelb", 0x07: "grün",
    0x08: "schwarz", 0x09: "transparent", 0x20: "weiß (matt)", 0x21: "transparent (matt)", 0x22: "silber (matt)",
    0x23: "gold (satin)", 0x24: "silber (satin)", 0x30: "blau", 0x31: "rot", 0x40: "signalorange",
    0x41: "signalgelb", 0x50: "rosa", 0x51: "hellgrau", 0x52: "apfelgrün", 0x60: "gelb", 0x61: "pink", 0x62: "blau",
    0x70: "weiß (Schrumpfschlauch)", 0x90: "weiß (Flexi)", 0x91: "gelb (Flexi)", 0xF0: "Reinigungsband",
    0xF1: "Schablonenband",
}
TEXT_COLORS = {0x01: "weiß", 0x02: "andere", 0x04: "rot", 0x05: "blau", 0x08: "schwarz", 0x0A: "gold", 0x62: "blau",
               0xF0: "Reinigungsband", 0xF1: "Schablonenband"}
STATUS_REPLY, PRINTING_COMPLETED, ERROR_OCCURRED, TURNED_OFF, NOTIFICATION, PHASE_CHANGE = 0, 1, 2, 4, 5, 6
PHASE_EDITING, PHASE_PRINTING = 0, 1


def is_status(record: bytes) -> bool:
    return len(record) == STATUS_SIZE and record[0] == 0x80 and record[1] == 0x20 and record[2] == ord("B")


def parse(record: bytes) -> dict:
    """The status record as JSON-friendly data; "errors" lists error codes (see ERRORS_1/ERRORS_2)."""
    if not is_status(record):
        raise ValueError(f"not a Brother status record: {record[:8].hex()}…")
    errors = [code for bit, code in ERRORS_1.items() if record[8] & bit]
    errors += [code for bit, code in ERRORS_2.items() if record[9] & bit and code not in errors]
    if record[11] == 0xFF and "wrong_media" not in errors:
        errors.append("wrong_media")
    return {
        "language": "ptouch",
        "ok": not errors,
        "errors": errors,
        "model_code": record[4],
        "media_width_mm": record[10],
        "media_type": MEDIA_TYPES.get(record[11], f"0x{record[11]:02x}"),
        "tape_color": TAPE_COLORS.get(record[24], ""),
        "text_color": TEXT_COLORS.get(record[25], ""),
        "status_type": record[18],
        "phase": "printing" if record[19] == PHASE_PRINTING else "ready",
    }


def split_records(data: bytes):
    """(status records, unread rest) of received bytes, skipping anything that is not a record."""
    found = []
    i = 0
    while i + STATUS_SIZE <= len(data):
        if is_status(data[i:i + STATUS_SIZE]):
            found.append(data[i:i + STATUS_SIZE])
            i += STATUS_SIZE
        else:
            i += 1
    return found, data[i:]


def records(data: bytes):
    return split_records(data)[0]


# Network printers known to answer over SNMP, and those that did not (not asked again for a while,
# as every attempt waits for the timeout). A printer that answered once is never given up: while
# printing it may not answer for a moment.
_snmp_answers = set()
_snmp_silent_until = {}
SNMP_RETRY_AFTER = 600


def snmp_status(device, timeout=2.0):
    """The status of a network printer over SNMP, or None (no SNMP, or not a network device)."""
    host = getattr(device, "host", None)
    if not host:
        return None
    key = (host, getattr(device, "snmp_port", snmp.DEFAULT_PORT))
    if key not in _snmp_answers and _snmp_silent_until.get(key, 0) > time.monotonic():
        return None
    record = snmp.get(host, STATUS_OID, port=key[1], timeout=timeout)
    if not (record and is_status(record)):
        if key not in _snmp_answers:
            _snmp_silent_until[key] = time.monotonic() + SNMP_RETRY_AFTER
        return None
    _snmp_answers.add(key)
    return parse(record)


def query(device, timeout=3.0):
    """The printer's status, or None if it did not answer: over SNMP for network printers that support
    it (remembered on the device for wait_until_printed), else by ESC i S on the connection."""
    status = snmp_status(device)
    device.status_by_snmp = status is not None
    if status is not None:
        return status
    device.drain()
    device.write(STATUS_REQUEST)
    data = device.read_until(lambda received: any(
        parse(record)["status_type"] == STATUS_REPLY for record in records(received)), timeout)
    replies = [parse(record) for record in records(data)]
    replies = [reply for reply in replies if reply["status_type"] == STATUS_REPLY] or replies
    return replies[-1] if replies else None


def wait_until_printed(device, pages, timeout):
    """Read the notifications after a job: ("done", status) once `pages` pages are printed,
    ("failed", status) on an error, ("sent", last status or None) if the time ran out."""
    if getattr(device, "status_by_snmp", False):
        return wait_by_snmp(device, timeout)
    deadline = time.monotonic() + timeout
    completed, buffer, last = 0, b"", None
    while time.monotonic() < deadline:
        chunk = device.read(4096, deadline - time.monotonic())
        if not chunk:
            break
        found, buffer = split_records(buffer + chunk)
        for record in found:
            last = parse(record)
            if last["status_type"] == ERROR_OCCURRED or last["errors"]:
                return "failed", last
            if last["status_type"] == PRINTING_COMPLETED:
                completed += 1
                if completed >= pages:
                    return "done", last
    return "sent", last


def wait_by_snmp(device, timeout, interval=0.5):
    """Poll the status over SNMP: done once the printer was printing and is ready again (or stayed ready
    for a few polls: a short label can be printed between two polls)."""
    deadline = time.monotonic() + timeout
    seen_printing, ready_polls, last = False, 0, None
    while time.monotonic() < deadline:
        time.sleep(interval)
        status = snmp_status(device)
        if status is None:
            continue
        last = status
        if status["errors"]:
            return "failed", status
        if status["phase"] == "printing":
            seen_printing, ready_polls = True, 0
            continue
        ready_polls += 1
        if seen_printing or ready_polls >= 6:
            return "done", status
    return "sent", last
