"""
Fake label printers for development and tests: TCP servers that answer like a Zebra (ZPL) and a
Brother P-touch on port 9100, including their status, and save what they "print".

    python -m label_printing.simulator --zebra 9101 --brother 9102 --out labels/

Configure printers in the admin as network printers on localhost:9101 / :9102. Zebra labels are
rendered by labelary.com (an external service with rate limits: test data only) to PNG, several to
one PDF; the ZPL is saved next to them. Brother raster data is decoded to PNG locally.

Error states (paper out, wrong tape, no answer, …) come from --zebra-errors/--brother-errors or,
while running, from a JSON state file (--state-file), re-read on every request:
    {"zebra": {"errors": ["paper_out"]}, "brother": {"tape_mm": 24, "silent": true}}
"""
import argparse
import io
import json
import logging
import re
import socketserver
import struct
import threading
import time
import urllib.error
from pathlib import Path

import packbits
from PIL import Image

from . import labelary as labelary_api
from .devices import brother, snmp, zebra

log = logging.getLogger("label_printing.simulator")



class PrinterState:
    """What the fake printer reports; errors are the codes of devices.brother / devices.zebra."""

    def __init__(self, errors=(), tape_mm=12, silent=False, state_file=None, name="", model_code=0x68,
                 tape_color=0x01, text_color=0x08, inband_status=True):
        self.errors, self.tape_mm, self.silent = list(errors), tape_mm, silent
        # Brother: what the status reports (model, tape and text colour codes: white tape, black print)
        self.model_code, self.tape_color, self.text_color = model_code, tape_color, text_color
        # Brother network printers like the PT-P900W answer status requests over SNMP only.
        self.inband_status = inband_status
        self.printing = False
        self.state_file, self.name = state_file, name
        self.lock = threading.Lock()

    def refresh(self):
        if not self.state_file:
            return
        try:
            data = json.loads(Path(self.state_file).read_text()).get(self.name, {})
        except (OSError, ValueError):
            return
        with self.lock:
            self.errors = list(data.get("errors", self.errors))
            self.tape_mm = data.get("tape_mm", self.tape_mm)
            self.silent = data.get("silent", self.silent)


class Output:
    """Where printed labels go: a directory, and a list for tests."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None
        self.printed = []
        self.counter = 0
        self.lock = threading.Lock()

    def save(self, prefix, extension, data):
        with self.lock:
            self.counter += 1
            name = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{self.counter}.{extension}"
            self.printed.append((name, data))
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / name).write_bytes(data)
            log.info("printed %s", self.directory / name)
        return name


def received(sock):
    """What a client sends, until it closes the connection (a reset is a normal end, too)."""
    try:
        while chunk := sock.recv(65536):
            yield chunk
    except (ConnectionResetError, BrokenPipeError):
        return


def send(sock, data):
    try:
        sock.sendall(data)
    except OSError:
        pass  # the client is gone


# ---------------------------------------------------------------- Brother P-touch

# Bytes per raster line → ptouch printer class with that print head
BROTHER_MODELS = {16: "PTE550W", 70: "PTP900W"}
ERROR_BITS_1 = {code: bit for bit, code in brother.ERRORS_1.items()}
ERROR_BITS_2 = {code: bit for bit, code in brother.ERRORS_2.items()}


def brother_status(state, status_type=brother.STATUS_REPLY, phase=brother.PHASE_EDITING, extra=()):
    errors = set(state.errors) | set(extra)
    error_1 = sum(bit for code, bit in ERROR_BITS_1.items() if code in errors)
    error_2 = sum(bit for code, bit in ERROR_BITS_2.items() if code in errors)
    media_type = 0x00 if "no_media" in errors else 0x01
    record = bytearray(brother.STATUS_SIZE)
    record[0:6] = bytes([0x80, 0x20, ord("B"), 0x30, state.model_code, 0x30])
    record[8], record[9] = error_1, error_2
    record[10] = 0 if "no_media" in errors else state.tape_mm
    record[11] = media_type
    record[18], record[19] = status_type, phase
    record[24], record[25] = state.tape_color, state.text_color
    return bytes(record)


class BrotherStream:
    """Parses the raster command stream as it arrives; calls back for status requests and printed pages."""

    def __init__(self, on_status_request=lambda: None, on_page=lambda page: None):
        self.buffer = b""
        self.on_status_request, self.on_page = on_status_request, on_page
        self.compression = 0
        self.width_mm = None
        self.lines = []

    def feed(self, data):
        self.buffer += data
        while self.buffer:
            consumed = self.step(self.buffer)
            if consumed == 0:
                return  # incomplete command, wait for more data
            self.buffer = self.buffer[consumed:]

    def step(self, data):
        first = data[0]
        if first == 0x00:
            return len(data) - len(data.lstrip(b"\x00"))
        if first == 0x1B:
            if len(data) < 2:
                return 0
            if data[1] == ord("@"):
                self.lines, self.compression = [], 0
                return 2
            if data[1] != ord("i"):
                return 1
            if len(data) < 3:
                return 0
            command = data[2]
            if command == ord("S"):
                self.on_status_request()
                return 3
            if command == ord("z"):
                if len(data) < 13:
                    return 0
                self.width_mm = data[5]
                return 13
            if command == ord("d"):
                return 5 if len(data) >= 5 else 0
            # ESC i a / M / A / K / ! with one parameter byte; anything unknown likewise.
            return 4 if len(data) >= 4 else 0
        if first == ord("M"):
            if len(data) < 2:
                return 0
            self.compression = data[1]
            return 2
        if first == ord("G"):
            if len(data) < 3:
                return 0
            size = struct.unpack("<H", data[1:3])[0]
            if len(data) < 3 + size:
                return 0
            line = data[3:3 + size]
            if self.compression == 0x02:
                line = packbits.decode(line)
            self.lines.append(bytes(line))
            return 3 + size
        if first == ord("Z"):
            self.lines.append(None)  # an empty line; its width is known once a full line came
            return 1
        if first in (0x0C, 0x1A):
            lines, self.lines = self.lines, []
            self.on_page({"lines": lines, "width_mm": self.width_mm, "feed": first == 0x1A})
            return 1
        return 1


def brother_page_image(page):
    """The printed area of a page as a 1-bit image in reading direction (black = 0), like the label image."""
    full = [line for line in page["lines"] if line is not None]
    bytes_per_line = len(full[0]) if full else 16
    lines = [line if line is not None else bytes(bytes_per_line) for line in page["lines"]]
    pins = bytes_per_line * 8
    image = Image.new("1", (len(lines), pins), 1)
    pixels = image.load()
    for x, line in enumerate(lines):
        for y in range(pins):
            if line[y // 8] & (0x80 >> (y % 8)):
                pixels[x, y] = 0
    # Crop to the tape's print area (ptouch's pin configuration), if known.
    try:
        import ptouch

        model = getattr(ptouch, BROTHER_MODELS[bytes_per_line])
        tape = next(t for t in model.PIN_CONFIGS if t.width_mm == page["width_mm"] and t.__name__.startswith("Tape"))
        config = model.PIN_CONFIGS[tape]
        image = image.crop((0, config.left_pins, image.width, config.left_pins + config.print_pins))
    except (ImportError, KeyError, StopIteration):
        pass
    return image


def decode_brother(data):
    """Pages (1-bit images) in a P-touch raster job."""
    pages = []
    BrotherStream(on_page=lambda page: pages.append(brother_page_image(page))).feed(data)
    return pages


class BrotherHandler(socketserver.BaseRequestHandler):
    def handle(self):
        state, output = self.server.state, self.server.output
        sock = self.request

        def reply(record):
            state.refresh()
            if not state.silent:
                send(sock, record)

        def page_done(page):
            state.refresh()
            wrong = page["width_mm"] not in (None, state.tape_mm)
            if state.errors or wrong:
                reply(brother_status(state, brother.ERROR_OCCURRED, extra=["wrong_media"] if wrong else ()))
                return
            reply(brother_status(state, brother.PHASE_CHANGE, brother.PHASE_PRINTING))
            state.printing = True
            time.sleep(self.server.seconds_per_page)
            image = brother_page_image(page)
            out = io.BytesIO()
            image.save(out, format="PNG")
            output.save("brother", "png", out.getvalue())
            state.printing = False
            reply(brother_status(state, brother.PRINTING_COMPLETED, brother.PHASE_PRINTING))
            reply(brother_status(state, brother.PHASE_CHANGE, brother.PHASE_EDITING))

        def status_request():
            if state.inband_status:
                reply(brother_status(state))

        stream = BrotherStream(on_status_request=status_request, on_page=page_done)
        for chunk in received(sock):
            stream.feed(chunk)


class BrotherSnmp(socketserver.BaseRequestHandler):
    """SNMP GET of the status record (brother.STATUS_OID), as Brother network printers answer it."""

    def handle(self):
        data, sock = self.request
        state = self.server.state
        state.refresh()
        if state.silent:
            return
        phase = brother.PHASE_PRINTING if state.printing else brother.PHASE_EDITING
        record = brother_status(state, brother.STATUS_REPLY, phase)
        sock.sendto(snmp.response(brother.STATUS_OID, record, request_id=snmp.request_id_of(data)), self.client_address)


# ---------------------------------------------------------------- Zebra ZPL

ZEBRA_ERROR_FIELDS = {"paper_out": (0, 1), "paused": (0, 2), "buffer_full": (0, 5), "system_error": (0, 9),
                      "temperature": (0, 11), "head_open": (1, 2)}


def zebra_identity(dpi):
    return zebra.STX + f"GK420t,V61.17.17Z,{round(dpi / 25.4)},8176KB".encode() + zebra.ETX + b"\r\n"


def zebra_status(state, formats=0, remaining=0):
    first = ["030", "0", "0", "0245", f"{formats:03d}", "0", "0", "0", "000", "0", "0", "0"]
    second = ["001", "0", "0", "0", "0", "2", "6", "0", f"{remaining:08d}", "1", "000"]
    for code in state.errors:
        if code in ZEBRA_ERROR_FIELDS:
            line, index = ZEBRA_ERROR_FIELDS[code]
            (first, second)[line][index] = "1"
    return b"".join(zebra.STX + ",".join(fields).encode() + zebra.ETX + b"\r\n"
                    for fields in (first, second, ["1234", "0"]))


def zpl_graphics(zpl):
    """The ^GFA images (uncompressed hex) in ZPL as 1-bit images, black = 0 like the label images."""
    images = []
    for total, row, data in re.findall(r"\^GFA,(\d+),\d+,(\d+),([0-9A-Fa-f]+)", zpl):
        raw = bytes.fromhex(data)
        height = int(total) // int(row)
        bits = Image.frombytes("1", (int(row) * 8, height), raw)
        images.append(Image.eval(bits.convert("L"), lambda value: 255 - value).convert("1"))
    return images


def zpl_label_count(zpl):
    """Labels printed by the formats in `zpl`: each format once, or as often as its ^PQ says."""
    count = 0
    for fmt in re.findall(r"\^XA.*?\^XZ", zpl, re.S):
        quantity = re.search(r"\^PQ(\d+)", fmt)
        count += int(quantity.group(1)) if quantity else 1
    return count or 1


def zpl_size_inches(zpl, dpi, default=(2.25, 1.25)):
    width, length = re.search(r"\^PW(\d+)", zpl), re.search(r"\^LL(\d+)", zpl)
    return (int(width.group(1)) / dpi if width else default[0], int(length.group(1)) / dpi if length else default[1])


def labelary(zpl, dpi=203, count=1):
    """(bytes, extension) of the labels rendered by labelary.com: PNG for one label, PDF for several."""
    width, height = zpl_size_inches(zpl, dpi)
    return labelary_api.render(zpl, dpi, width, height, count)


class ZebraPrinter:
    """The printer behind the connections: formats wait in its buffer while it has an error."""

    def __init__(self, state, output, dpi=203, render=labelary, seconds_per_label=0.3):
        self.state, self.output, self.dpi, self.render = state, output, dpi, render
        self.seconds_per_label = seconds_per_label
        self.queue, self.remaining = [], 0
        self.lock = threading.Lock()
        self.wake, self.stopped = threading.Event(), threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def status(self):
        with self.lock:
            return zebra_status(self.state, len(self.queue), self.remaining)

    def add(self, zpl):
        with self.lock:
            self.queue.append(zpl)
        self.wake.set()

    def run(self):
        while not self.stopped.is_set():
            self.wake.wait(0.2)
            self.wake.clear()
            self.state.refresh()
            with self.lock:
                if self.state.errors or not self.queue:
                    continue
                zpl = self.queue.pop(0)
                self.remaining = zpl_label_count(zpl)
            time.sleep(self.seconds_per_label * self.remaining)
            self.print(zpl)
            with self.lock:
                self.remaining = 0

    def print(self, zpl):
        self.output.save("zebra", "zpl", zpl.encode("utf-8"))
        if self.render is None:
            return
        try:
            data, extension = self.render(zpl, self.dpi, zpl_label_count(zpl))
        except (OSError, urllib.error.URLError) as error:
            log.warning("rendering failed, only the ZPL is saved: %s", error)
            return
        self.output.save("zebra", extension, data)


class ZebraHandler(socketserver.BaseRequestHandler):
    def handle(self):
        printer, state = self.server.printer, self.server.state
        buffer = ""
        for chunk in received(self.request):
            buffer += chunk.decode("utf-8", "replace")
            while "~HS" in buffer:
                buffer = buffer.replace("~HS", "", 1)
                state.refresh()
                if not state.silent:
                    send(self.request, printer.status())
            while "~HI" in buffer:
                buffer = buffer.replace("~HI", "", 1)
                if not state.silent:
                    send(self.request, zebra_identity(printer.dpi))
            while (start := buffer.find("^XA")) != -1 and (end := buffer.find("^XZ", start)) != -1:
                printer.add(buffer[start:end + 3])
                buffer = buffer[end + 3:]


# ---------------------------------------------------------------- servers

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    printer = None

    @property
    def port(self):
        return self.server_address[1]

    snmp = None

    def stop(self):
        self.shutdown()
        self.server_close()
        if self.printer:
            self.printer.stopped.set()
        if self.snmp:
            self.snmp.shutdown()
            self.snmp.server_close()


class UdpServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True

    @property
    def port(self):
        return self.server_address[1]


def start(kind, port=0, host="127.0.0.1", state=None, output=None, snmp_port=None, seconds_per_page=0.0,
          **options):
    """A running fake printer ("zebra" or "brother") in a background thread; .port is its port. A Brother
    with snmp_port (0: any free port) also answers SNMP there (.snmp.port)."""
    state = state or PrinterState(name=kind)
    output = output or Output()
    server = Server((host, port), ZebraHandler if kind == "zebra" else BrotherHandler)
    server.state, server.output, server.seconds_per_page = state, output, seconds_per_page
    if kind == "zebra":
        server.printer = ZebraPrinter(state, output, **options)
    elif snmp_port is not None:
        server.snmp = UdpServer((host, snmp_port), BrotherSnmp)
        server.snmp.state = state
        threading.Thread(target=server.snmp.serve_forever, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def split(value):
    return [code for code in value.split(",") if code]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zebra", type=int, metavar="PORT", help="run a Zebra (ZPL) printer on this port")
    parser.add_argument("--brother", type=int, metavar="PORT", help="run a Brother P-touch printer on this port")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--out", default="labels", help="directory for printed labels (default: labels/)")
    parser.add_argument("--zebra-dpi", type=int, default=203)
    parser.add_argument("--zebra-errors", default="", help="comma-separated, e.g. paper_out,paused,head_open")
    parser.add_argument("--no-render", action="store_true", help="save Zebra labels as ZPL only (no labelary)")
    parser.add_argument("--brother-tape", type=int, default=12, help="loaded tape width in mm (default 12)")
    parser.add_argument("--brother-errors", default="", help="comma-separated, e.g. cover_open,no_media")
    parser.add_argument("--brother-snmp", type=int, metavar="PORT",
                        help="answer status requests over SNMP on this UDP port only, like a PT-P900W on the network")
    parser.add_argument("--state-file", help="JSON file with error states, re-read on every request")
    args = parser.parse_args()
    if not (args.zebra or args.brother):
        parser.error("give --zebra PORT and/or --brother PORT")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    output = Output(args.out)
    if args.zebra:
        state = PrinterState(split(args.zebra_errors), state_file=args.state_file, name="zebra")
        start("zebra", args.zebra, args.host, state, output, dpi=args.zebra_dpi,
              render=None if args.no_render else labelary)
        log.info("Zebra printer on %s:%s", args.host, args.zebra)
    if args.brother:
        state = PrinterState(split(args.brother_errors), args.brother_tape, state_file=args.state_file, name="brother",
                             inband_status=args.brother_snmp is None)
        start("brother", args.brother, args.host, state, output, snmp_port=args.brother_snmp, seconds_per_page=0.5)
        log.info("Brother P-touch printer (%s mm tape) on %s:%s", args.brother_tape, args.host, args.brother)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
