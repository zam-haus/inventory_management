"""QR codes for ZAM IDs: always version 1, alphanumeric (ZAM-ID-SPEC.md §8.1)."""
import io

import segno

URL_PREFIX = "HTTPS://I.ZAM.HAUS/"


def make(code: str) -> segno.QRCode:
    qr = segno.make(URL_PREFIX + code, error="l", micro=False, boost_error=False)
    if qr.version != 1 or qr.mode != "alphanumeric":
        raise ValueError(f"QR for {code} is version {qr.version}/{qr.mode}, expected 1/alphanumeric")
    return qr


def svg(code: str, scale: int = 4) -> bytes:
    out = io.BytesIO()
    make(code).save(out, kind="svg", scale=scale, border=4, xmldecl=False, svgns=True)
    return out.getvalue()


def png(code: str, scale: int = 8) -> bytes:
    out = io.BytesIO()
    make(code).save(out, kind="png", scale=scale, border=4)
    return out.getvalue()
