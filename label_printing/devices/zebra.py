"""
Zebra ZPL status: the host status return (~HS, ZPL II programming guide).

The printer answers ~HS with three lines, each framed by STX (0x02) and ETX (0x03):
  1: aaa,b,c,dddd,eee,f,g,h,iii,j,k,l   paper out b, pause c, formats in buffer eee, buffer full f,
                                         partial format h, corrupt RAM j, under/over temperature k/l
  2: mmm,n,o,p,q,r,s,t,uuuuuuuu,v,www   head up o, ribbon out p, thermal transfer q, labels remaining u
  3: xxxx,y                             password, static RAM
"""
import time

STATUS_REQUEST = b"~HS"
STX, ETX = b"\x02", b"\x03"


def lines(data: bytes):
    """The STX…ETX framed lines in received bytes."""
    found = []
    for part in data.split(STX)[1:]:
        if ETX in part:
            found.append(part.split(ETX, 1)[0].decode("ascii", "replace"))
    return found


def parse(data: bytes) -> dict:
    """The ~HS answer as JSON-friendly data; "errors" lists error codes."""
    found = lines(data)
    if len(found) < 2:
        raise ValueError(f"not a Zebra host status: {data[:40]!r}")
    first, second = found[0].split(","), found[1].split(",")
    if len(first) < 12 or len(second) < 9:
        raise ValueError(f"not a Zebra host status: {data[:40]!r}")
    errors = []
    if flag(first[1]):
        errors.append("paper_out")
    if flag(first[2]):
        errors.append("paused")
    if flag(first[5]):
        errors.append("buffer_full")
    if flag(first[9]):
        errors.append("system_error")
    if flag(first[10]) or flag(first[11]):
        errors.append("temperature")
    if flag(second[2]):
        errors.append("head_open")
    # The ribbon only matters when printing thermal transfer.
    if flag(second[3]) and flag(second[4]):
        errors.append("ribbon_out")
    formats, remaining = int(first[4] or 0), int(second[8] or 0)
    return {
        "language": "zpl",
        "ok": not errors,
        "errors": errors,
        "formats_in_buffer": formats,
        "labels_remaining": remaining,
        "partial_format": flag(first[7]),
        "label_length_dots": int(first[3] or 0),
        "thermal_transfer": flag(second[4]),
        "phase": "printing" if formats or remaining or flag(first[7]) else "ready",
    }


IDENTIFY_REQUEST = b"~HI"
DOTS_PER_MM = {6: 152, 8: 203, 12: 300, 24: 600}


def identify(device, timeout=3.0):
    """Model, firmware and resolution from ~HI ("GK420t,V61.17.17Z,8,8176KB"), or None."""
    device.drain()
    device.write(IDENTIFY_REQUEST)
    found = lines(device.read_until(lambda data: bool(lines(data)), timeout))
    if not found:
        return None
    fields = [field.strip() for field in found[0].split(",")]
    info = {"model": fields[0], "firmware": fields[1] if len(fields) > 1 else ""}
    if len(fields) > 2 and fields[2].isdigit():
        info["dpi"] = DOTS_PER_MM.get(int(fields[2]), round(int(fields[2]) * 25.4))
    return info


def flag(value: str) -> bool:
    return value.strip() == "1"


def complete(data: bytes) -> bool:
    return len(lines(data)) >= 3


def query(device, timeout=3.0):
    """The printer's status, or None if it did not answer."""
    device.drain()
    device.write(STATUS_REQUEST)
    data = device.read_until(complete, timeout)
    try:
        return parse(data)
    except ValueError:
        return None


def wait_until_printed(device, pages, timeout, interval=0.3):
    """Poll ~HS after a job: ("done", status) once the printer is idle again, ("failed", status)
    on an error, ("sent", last status or None) if the time ran out.

    ~HS is answered at once, possibly before the printer parsed the job; so "idle" counts only after
    it was seen busy, or after it stayed idle for a few polls."""
    deadline = time.monotonic() + timeout
    seen_busy, idle_polls, last = False, 0, None
    while time.monotonic() < deadline:
        time.sleep(interval)
        status = query(device, timeout=min(3.0, max(deadline - time.monotonic(), 0.1)))
        if status is None:
            continue
        last = status
        if status["errors"]:
            return "failed", status
        if status["phase"] == "printing":
            seen_busy = True
            idle_polls = 0
            continue
        idle_polls += 1
        if seen_busy or idle_polls >= 3:
            return "done", status
    return "sent", last
