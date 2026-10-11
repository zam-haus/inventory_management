"""
Brother P-touch labels for ZAM IDs. zamlabel.py is integrated as-is; this module
only wraps it for the app (PNG bytes, ZIP batches).
"""
import functools
import io
import zipfile

from . import zamlabel

# zamlabel fits font sizes by rendering trial glyphs, which takes seconds per label
# at 360 dpi. The fits depend only on (font, size, weight) and the logo only on the
# QR size, so memoize them here; zamlabel.py itself stays unchanged. Results are
# identical (see tests). Cached images are only pasted, never modified.
zamlabel._font = functools.lru_cache(maxsize=None)(zamlabel._font)
zamlabel._cap_height = functools.lru_cache(maxsize=None)(zamlabel._cap_height)
zamlabel.vertical_logo = functools.lru_cache(maxsize=None)(zamlabel.vertical_logo)

PROFILES = zamlabel.PROFILES
PRINTERS = sorted({printer for printer, _tape in PROFILES})
# Shown on screen (info page, admin): 360 dpi, 320 dots tall, crisp at half size on HiDPI screens.
PREVIEW = ("P900", 24)


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
