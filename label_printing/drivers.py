"""
Print data for the printer languages: ZPL for Zebra, the P-touch raster format for Brother.

A job is built when it is submitted (label_printing.services) and sent later as plain bytes, so
neither the Celery worker nor the print agent needs to know about layouts or ptouch.
"""
import math

import ptouch
from PIL import Image
from ptouch.connection import Connection

# Printer.model choices for P-touch printers → ptouch printer classes.
PTOUCH_MODELS = {
    "E550W": ptouch.PTE550W,
    "P750W": ptouch.PTP750W,
    "P900": ptouch.PTP900,
    "P900W": ptouch.PTP900W,
    "P950NW": ptouch.PTP950NW,
}
# Tape widths (mm, as on the cassette) → ptouch tape classes; 3.5 mm tape reports 4 mm.
PTOUCH_TAPES = {
    4: ptouch.Tape3_5mm,
    6: ptouch.Tape6mm,
    9: ptouch.Tape9mm,
    12: ptouch.Tape12mm,
    18: ptouch.Tape18mm,
    24: ptouch.Tape24mm,
    36: ptouch.Tape36mm,
}


def mm_to_dots(mm, dpi):
    return round(mm * dpi / 25.4)


def black_bits(image: Image.Image) -> Image.Image:
    """A 1-bit copy where black pixels are 1 bits (PIL's mode "1" stores white as 1)."""
    return image.convert("L").point(lambda value: 255 if value < 128 else 0).convert("1")


# ---------------------------------------------------------------- ZPL


def zpl_graphic(image: Image.Image) -> str:
    """^GFA field data (uncompressed hex) for a 1-bit image; no firmware needs anything special for it."""
    bytes_per_row = math.ceil(image.width / 8)
    data = black_bits(image).tobytes()
    return f"^GFA,{len(data)},{len(data)},{bytes_per_row},{data.hex().upper()}"


# Print quality on a Zebra is its speed (^PR, inches per second; a printer slows down to its maximum):
# slower prints cleaner. Standard leaves the printer's own setting.
ZPL_SPEEDS = {"draft": 6, "standard": None, "high": 2}


def zpl_speed(quality):
    speed = ZPL_SPEEDS.get(quality)
    return f"^PR{speed}" if speed else ""


def zpl_raster_label(image: Image.Image, copies=1, offset=(0, 0), darkness=None, quality="standard") -> str:
    """One ZPL format printing `image` at the label's top left, `copies` times."""
    darkness = f"^MD{darkness}" if darkness is not None else ""
    return (f"^XA^PW{image.width}^LL{image.height}^LH{offset[0]},{offset[1]}{darkness}{zpl_speed(quality)}"
            f"^FO0,0{zpl_graphic(image)}^FS^PQ{copies}^XZ")


def zpl_with_quality(zpl, quality):
    """A template's format with the print speed of `quality` (right after ^XA)."""
    speed = zpl_speed(quality)
    return zpl.replace("^XA", "^XA" + speed, 1) if speed else zpl


def zpl_job(formats, copies=1) -> bytes:
    """ZPL formats (each ^XA…^XZ) repeated `copies` times; raster labels carry ^PQ themselves."""
    return "".join(zpl for zpl in formats for _ in range(copies)).encode("utf-8")


# ---------------------------------------------------------------- Brother P-touch


class BufferConnection(Connection):
    """Collects what a ptouch printer object would send, so the job can travel as bytes."""

    def __init__(self):
        self.data = bytearray()

    def connect(self, printer):
        pass

    def write(self, payload):
        self.data += payload

    def close(self):
        pass


def ptouch_tape(width_mm):
    try:
        return PTOUCH_TAPES[width_mm]
    except KeyError:
        raise ValueError(f"no P-touch tape of {width_mm} mm") from None


def ptouch_print_pins(model, tape_mm):
    """Height in dots of a label image for this printer and tape (the printable width of the tape)."""
    return PTOUCH_MODELS[model].PIN_CONFIGS[ptouch_tape(tape_mm)].print_pins


def ptouch_dpi(model):
    return PTOUCH_MODELS[model].RESOLUTION_DPI


def ptouch_printer(model, quality):
    """The ptouch printer class for `model`, printing in `quality`:

    * draft: the printer's draft mode (ESC i K bit 0), faster and lighter,
    * high: high resolution (twice the dots along the tape). The label images are then already twice as
      long in dots (ptouch_high_resolution_dpi), so every raster line is sent once, not doubled as ptouch
      would do."""
    base = PTOUCH_MODELS[model]
    if quality == "draft":
        class Draft(base):
            def _cmd_advanced_mode_settings(self, *args, **kwargs):
                command = bytearray(super()._cmd_advanced_mode_settings(*args, **kwargs))
                command[3] |= 0x01
                return bytes(command)
        return Draft
    if quality == "high":
        class HighResolution(base):
            def _build_page_control_sequence(self, num_lines, *args, **kwargs):
                return super()._build_page_control_sequence(num_lines // 2, *args, **kwargs)  # doubled again

            def _build_raster_data(self, raster, num_lines, high_resolution):
                return super()._build_raster_data(raster, num_lines, False)
        return HighResolution
    return base


def ptouch_high_resolution_dpi(model):
    """Dots per inch along the tape in high resolution (across it, the resolution stays the same)."""
    return PTOUCH_MODELS[model].RESOLUTION_DPI_HIGH


def ptouch_job(model, tape_mm, images, copies=1, quality="standard", offset=0):
    """(bytes, pages): the labels, with half cuts between them when there are several. In high quality the
    images are twice as long in dots (see ptouch_printer). offset moves the print area across the tape by
    that many print head pins, positive = down as the label is read (image row 0 is the top row), for
    printers whose tape sits a little apart from the pins Brother's specification gives."""
    tape = ptouch_tape(tape_mm)
    pins = ptouch_print_pins(model, tape_mm)
    labels = []
    for image in images:
        if image.height != pins:
            raise ValueError(f"label image is {image.height} dots high, the {tape_mm} mm tape needs {pins}")
        labels.extend(ptouch.Label(image.convert("1"), tape) for _ in range(copies))
    connection = BufferConnection()
    printer = ptouch_printer(model, quality)(connection, high_resolution=quality == "high")
    if offset:
        config = printer.PIN_CONFIGS[tape]
        offset = max(-config.left_pins, min(offset, config.right_pins))
        printer.PIN_CONFIGS = {**printer.PIN_CONFIGS, tape: ptouch.TapeConfig(
            config.left_pins + offset, config.print_pins, config.right_pins - offset)}
    if len(labels) == 1:
        printer.print(labels[0])
    else:
        printer.print_multi(labels, half_cut=True)
    return bytes(connection.data), len(labels)
