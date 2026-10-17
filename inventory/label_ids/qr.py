"""QR codes for label IDs: alphanumeric, version 1 with the production base URL (LABEL-ID-SPEC.md §8.1)."""
import io

import segno
from django.conf import settings


def url_prefix() -> str:
    """settings.LABEL_ID_BASE_URL in QR form: uppercase, one trailing slash (HTTPS://I.ZAM.HAUS/)."""
    return getattr(settings, "LABEL_ID_BASE_URL", "https://i.zam.haus/").rstrip("/").upper() + "/"


def make(code: str) -> segno.QRCode:
    qr = segno.make(url_prefix() + code, error="l", micro=False, boost_error=False)
    if qr.mode != "alphanumeric":
        raise ValueError(f"QR for {code} is in {qr.mode} mode, expected alphanumeric")
    return qr


def svg(code: str, scale: int = 4) -> bytes:
    out = io.BytesIO()
    make(code).save(out, kind="svg", scale=scale, border=4, xmldecl=False, svgns=True)
    return out.getvalue()


def png(code: str, scale: int = 8) -> bytes:
    out = io.BytesIO()
    make(code).save(out, kind="png", scale=scale, border=4)
    return out.getvalue()
