"""
Brother P-touch labels for ZAM IDs. zamlabel.py is integrated as-is; this module
only wraps it for the app (PNG bytes, ZIP batches).
"""
import io
import zipfile

from . import zamlabel

PROFILES = zamlabel.PROFILES
PRINTERS = sorted({printer for printer, _tape in PROFILES})


def tapes(printer):
    return sorted(tape for p, tape in PROFILES if p == printer)


def filename(code, printer, tape):
    return f"{code}_{printer}_{tape}mm.png"


def render(code, printer, tape):
    """1-bit PNG for one label, pixel-exact for the printer; print in standard resolution."""
    if (printer, tape) not in PROFILES:
        raise ValueError(f"no label profile for {printer} with {tape} mm tape")
    img, info = zamlabel.compose(code, printer, tape)
    out = io.BytesIO()
    img.save(out, format="PNG", dpi=(info["dpi"], info["dpi"]))
    return out.getvalue()


def render_zip(codes, printer, tape):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for code in codes:
            archive.writestr(filename(code, printer, tape), render(code, printer, tape))
    return out.getvalue()
