"""
Brother P-touch labels for label IDs. idlabel.py is integrated as-is; this module
only wraps it for the app (PNG bytes, ZIP batches, base URL and logo text from settings).
"""
import functools
import io
import zipfile

from .. import naming, qr
from . import idlabel

# idlabel fits font sizes by rendering trial glyphs, which takes seconds per label
# at 360 dpi. The fits depend only on (font, size, weight) and the logo only on the
# QR size, so memoize them here; idlabel.py itself stays unchanged. Results are
# identical (see tests). Cached images are only pasted, never modified.
idlabel._font = functools.lru_cache(maxsize=None)(idlabel._font)
idlabel._cap_height = functools.lru_cache(maxsize=None)(idlabel._cap_height)
_vertical_logo = idlabel.vertical_logo


@functools.lru_cache(maxsize=None)
def _cached_logo(q, kind, logo_path, text):
    return _vertical_logo(q, kind, logo_path)  # draws idlabel.LOGO_TEXT, which is `text` here


def _vertical_logo_cached(q, kind, logo_path=None):
    return _cached_logo(q, kind, logo_path, idlabel.LOGO_TEXT)


_vertical_logo_cached.__wrapped__ = _vertical_logo
idlabel.vertical_logo = _vertical_logo_cached

PROFILES = idlabel.PROFILES
PRINTERS = sorted({printer for printer, _tape in PROFILES})
# Shown on screen (info page, admin): 360 dpi, 320 dots tall, crisp at half size on HiDPI screens.
PREVIEW = ("P900", 24)


def tapes(printer):
    return sorted(tape for p, tape in PROFILES if p == printer)


def filename(code, printer, tape):
    return f"{code}_{printer}_{tape}mm.png"


def image(code, printer, tape):
    """The label as a 1-bit image, pixel-exact for the printer (as tall as the tape's print area);
    print in standard resolution."""
    if (printer, tape) not in PROFILES:
        raise ValueError(f"no label profile for {printer} with {tape} mm tape")
    # idlabel reads URL prefix and logo text from module constants; use the settings instead.
    previous = idlabel.URL_PREFIX, idlabel.LOGO_TEXT
    idlabel.URL_PREFIX, idlabel.LOGO_TEXT = qr.url_prefix(), naming.name()
    try:
        return idlabel.compose(code, printer, tape)[0]
    finally:
        idlabel.URL_PREFIX, idlabel.LOGO_TEXT = previous


def render(code, printer, tape):
    """1-bit PNG for one label (see image)."""
    dpi = PROFILES[(printer, tape)][0] if (printer, tape) in PROFILES else 0
    out = io.BytesIO()
    image(code, printer, tape).save(out, format="PNG", dpi=(dpi, dpi))
    return out.getvalue()


def render_zip(codes, printer, tape):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for code in codes:
            archive.writestr(filename(code, printer, tape), render(code, printer, tape))
    return out.getvalue()
