#!/usr/bin/env python3
"""
idlabel.py – pixel-exact ZAM inventory labels for Brother PT-E550W and PT-P900(W)/P950NW.

Every element is placed on the printer's native dot grid:
  * image height == printable pins for the tape (no driver scaling)
  * QR modules are an integer number of dots, version 1, alphanumeric mode
  * text is rendered without anti-aliasing at an exact cap height in dots
  * the official ZAM Bildmarke (SVG) is rasterised at an exact dot height, or a hand-tuned
    1-bit bitmap for that height is used if present

Print in STANDARD resolution (180x180 / 360x360). The "high resolution" modes
only double the feed direction, which makes pixels non-square and breaks the grid.

Usage:
  python idlabel.py K7R4XD --printer E550W --tape 12 -o out.png
  python idlabel.py K7R4XD --all --preview preview.png
"""
import argparse
import os
import sys

import segno
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_ID = os.path.join(HERE, "fonts", "RobotoMono%5Bwght%5D.ttf")   # weight 700 (max of the font)
FONT_LOGO = os.path.join(HERE, "fonts", "Raleway%5Bwght%5D.ttf")
LOGO_TEXT = "ZAMid"
LOGO_DEFAULT = os.path.join(HERE, "zam-bildmarke.svg")   # from the ZAM design system, assets/Logos
URL_PREFIX = "HTTPS://I.ZAM.HAUS/"

# Printable pins per tape (Brother raster command reference, as used by the `ptouch` library)
# and the chosen dots per QR module.  module_mm = dots * 25.4 / dpi
PROFILES = {
    # printer, tape_mm : (dpi, print_pins, dots_per_module, logo, note)
    # logo: "text" = LOGO_TEXT set in Raleway, "mark" = official ZAM Bildmarke (SVG, currently unused)
    ("E550W", 9):  (180,  50,  2, "text", "0.28 mm modules - close-range only, test first"),
    ("E550W", 12): (180,  70,  3, "text", "0.42 mm modules - recommended small label"),
    ("E550W", 18): (180, 112,  4, "text", "0.56 mm modules"),
    ("E550W", 24): (180, 128,  5, "text", "0.71 mm modules"),
    ("P900", 9):   (360, 106,  4, "text", "0.28 mm modules - close-range only, test first"),
    ("P900", 12):  (360, 150,  6, "text", "0.42 mm modules - recommended small label"),
    ("P900", 18):  (360, 234,  9, "text", "0.64 mm modules"),
    ("P900", 24):  (360, 320, 12, "text", "0.85 mm modules"),
    ("P900", 36):  (360, 454, 18, "text", "1.27 mm modules"),
}


# ---------------------------------------------------------------- building blocks
def _qr(id_: str):
    # Version 1 with the production URL_PREFIX; longer prefixes (local testing) need larger versions.
    qr = segno.make(URL_PREFIX + id_, error="l", micro=False, boost_error=False)
    if qr.mode != "alphanumeric":
        sys.exit(f"QR is in {qr.mode} mode, expected alphanumeric")
    return qr


def qr_bitmap(id_: str, m: int) -> Image.Image:
    rows = [list(r) for r in _qr(id_).matrix]
    n = len(rows)
    img = Image.new("1", (n * m, n * m), 1)
    px = img.load()
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                for dy in range(m):
                    for dx in range(m):
                        px[x * m + dx, y * m + dy] = 0
    return img


def _ink_bbox(img):
    inv = Image.eval(img.convert("L"), lambda v: 255 - v)
    return inv.getbbox()


def _font(path, size, weight):
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _cap_height(f) -> int:
    probe = Image.new("1", (f.size * 4, f.size * 3), 1)
    d = ImageDraw.Draw(probe)
    d.fontmode = "1"
    d.text((f.size, f.size * 2), "H", font=f, fill=0, anchor="ls")
    bb = _ink_bbox(probe)
    return bb[3] - bb[1]


def text_line(text: str, font_path: str, cap_px: int, weight: int, tracking: int = 0):
    """
    Render one line 1-bit, no anti-aliasing, capitals exactly cap_px tall.
    Returns (bitmap cropped to ink, cap_top, baseline): rows inside the bitmap where the
    top of a flat capital (H) and the baseline sit, so lines can be aligned on those rows
    regardless of overshoots (O, Q) or tails.
    """
    f = None
    for size in range(4, cap_px * 3):
        cand = _font(font_path, size, weight)
        if _cap_height(cand) <= cap_px:
            f = cand
        else:
            break
    cap = _cap_height(f)
    w = int(sum(f.getlength(c) for c in text) + tracking * len(text) + cap_px * 4)
    hgt = cap_px * 4
    base_y = cap_px * 3
    img = Image.new("1", (w, hgt), 1)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    x = cap_px
    for c in text:
        d.text((x, base_y), c, font=f, fill=0, anchor="ls")
        x += f.getlength(c) + tracking
    bb = _ink_bbox(img)
    # the H probe's ink ends on row base_y-1 and starts on row base_y-cap
    return img.crop(bb), (base_y - cap) - bb[1], base_y - bb[1]


def text_bitmap(text: str, font_path: str, cap_px: int, weight: int, tracking: int = 0) -> Image.Image:
    return text_line(text, font_path, cap_px, weight, tracking)[0]


def _svg_to_1bit(path: str, height: int, threshold: int = 90) -> Image.Image:
    """
    Rasterise an SVG to exactly `height` dots. A dot is black only if it is ~65 % covered
    (grey < 90): keeps the thin gaps of the Z open at 13-20 dots and offsets thermal dot gain.
    """
    import io
    import re
    import cairosvg
    svg = open(path, encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    width = round(height * vb[2] / vb[3])
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=width, output_height=height,
                           background_color="white")
    g = Image.open(io.BytesIO(png)).convert("L")
    return g.point(lambda v: 0 if v < threshold else 255).convert("1", dither=Image.Dither.NONE)


def logo_bitmap(height: int, logo_path: str | None) -> Image.Image:
    """
    Order of preference for a logo `height` dots tall (horizontal orientation):
      1. hand-tuned bitmap  <logo>_<height>.png  next to the logo file
      2. the SVG (official ZAM Bildmarke) rasterised at exactly that height
      3. a PNG master, thresholded
      4. placeholder wordmark in Raleway
    """
    if logo_path and os.path.exists(logo_path):
        base, _ = os.path.splitext(logo_path)
        tuned = f"{base}_{height}.png"
        if os.path.exists(tuned):
            return Image.open(tuned).convert("1", dither=Image.Dither.NONE)
        if logo_path.lower().endswith(".svg"):
            return _svg_to_1bit(logo_path, height)
        src = Image.open(logo_path).convert("L")
        w = round(src.width * height / src.height)
        g = src.resize((w, height), Image.Resampling.LANCZOS)
        return g.point(lambda v: 255 if v > 127 else 0).convert("1", dither=Image.Dither.NONE)
    return text_bitmap("ZAM", FONT_LOGO, height, weight=800)


# ---------------------------------------------------------------- layouts
def vertical_logo(q: int, kind: str, logo_path=None) -> Image.Image:
    """
    The logo rotated 90 deg CCW (reads bottom-to-top), as long as possible but <= QR height.
    kind "text": LOGO_TEXT ("ZAMid", the app sets settings.LABEL_ID_NAME) in Raleway ExtraBold;
    kind "mark": official ZAM Bildmarke SVG.
    """
    h = round(q * 0.45)
    while h > 3:
        if kind == "text":
            lg = text_bitmap(LOGO_TEXT, FONT_LOGO, h, weight=800, tracking=0)
        else:
            lg = logo_bitmap(h, logo_path)
        if lg.width <= q:
            return lg.transpose(Image.Transpose.ROTATE_90)
        h -= 1
    raise ValueError("logo does not fit")


def compose(id_: str, printer: str, tape: int, logo_path=None):
    """
    ZAM (vertical) | QR | "K7R" / "-" / "4XR"
    Line 1: top of the capitals on the QR's first pixel row.
    Line 2: lowest ink on the QR's last pixel row.
    Hyphen: centred horizontally in the text column and vertically between the lines.
    """
    dpi, H, m, logo_kind, note = PROFILES[(printer, tape)]
    m = min(m, H // _qr(id_).symbol_size(border=0)[1])  # a larger QR version must still fit the tape
    qr = qr_bitmap(id_, m)
    q = qr.height
    # ZAM design system: QR quiet zone >= 4 modules (qr-ruhezone)
    lead, gap_logo, gap_qr, tail = m, 4 * m, 4 * m, 2 * m
    top = (H - q) // 2
    bottom = top + q - 1                     # last QR pixel row
    track = max(1, m // 2)

    logo = vertical_logo(q, logo_kind, logo_path)
    line_h = round(q * 0.38)
    l1, l1_cap, l1_base = text_line(id_[:3], FONT_ID, line_h, weight=700, tracking=track)
    l2, l2_cap, _ = text_line(id_[3:], FONT_ID, line_h, weight=700, tracking=track)
    hy = text_bitmap("-", FONT_ID, line_h, weight=700)
    y1 = top - l1_cap                        # flat cap tops of line 1 -> first QR row
    y2 = bottom + 1 - l2.height              # lowest ink of line 2    -> last QR row

    text_w = max(l1.width, l2.width)
    W = lead + logo.width + gap_logo + q + gap_qr + text_w + tail
    img = Image.new("1", (W, H), 1)
    img.paste(logo, (lead, top + (q - logo.height) // 2))
    xq = lead + logo.width + gap_logo
    img.paste(qr, (xq, top))
    x0 = xq + q + gap_qr
    img.paste(l1, (x0, y1))
    img.paste(l2, (x0, y2))
    # hyphen centred in the text column, vertically centred between the baseline of
    # line 1 and the cap tops of line 2
    gap_top, gap_bot = y1 + l1_base, y2 + l2_cap
    img.paste(hy, (x0 + (text_w - hy.width) // 2, (gap_top + gap_bot - hy.height) // 2))

    mm = 25.4 / dpi
    tape_margin = (tape - H * mm) / 2
    info = {
        "printer": printer, "tape": tape, "dpi": dpi, "logo": logo_kind,
        "pixels": f"{W}x{H}", "size_mm": f"{W*mm:.1f} x {tape}",
        "module": f"{m} dots = {m*mm:.2f} mm", "qr_mm": f"{q*mm:.1f}",
        "logo_dots": f"{logo.width}x{logo.height}",
        "quiet_vert_modules": f"{(top*mm + tape_margin)/(m*mm):.1f}",
        "note": note,
    }
    return img, info


def verify(img: Image.Image, id_: str, module_dots: int) -> bool:
    try:
        import cv2, numpy as np
    except ImportError:
        return True
    k = max(1, round(8 / module_dots))  # ~8 px per module for the detector
    big = img.resize((img.width * k, img.height * k), Image.Resampling.NEAREST).convert("L")
    pad = Image.new("L", (big.width + 200, big.height + 200), 255)
    pad.paste(big, (100, 100))
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(np.array(pad))
    return data == URL_PREFIX + id_


def preview_sheet(items, path, px_per_mm=12):
    """Everything at the same physical scale, tape drawn in grey, with captions."""
    font = ImageFont.truetype(FONT_ID, 22)
    rows = []
    for img, info in items:
        s = px_per_mm * 25.4 / info["dpi"]
        s = round(s)
        lab = img.resize((img.width * s, img.height * s), Image.Resampling.NEAREST)
        tape_px = round(info["tape"] * px_per_mm)
        strip = Image.new("RGB", (lab.width + 2 * px_per_mm, tape_px), (232, 232, 232))
        strip.paste(Image.new("RGB", (lab.width, tape_px), "white"), (px_per_mm, 0))
        strip.paste(lab.convert("RGB"), (px_per_mm, (tape_px - lab.height) // 2))
        cap = (f"PT-{info['printer']}  {info['tape']} mm  [logo: {info['logo']}]   "
               f"{info['size_mm']} mm   module {info['module']}   QR {info['qr_mm']} mm")
        rows.append((strip, cap))
    W = max(max(r.width for r, _ in rows), 1100) + 40
    H = sum(r.height + 50 for r, _ in rows) + 20
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    y = 15
    for r, cap in rows:
        d.text((20, y), cap, font=font, fill=(60, 60, 60))
        sheet.paste(r, (20, y + 30))
        y += r.height + 50
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--printer", choices=["E550W", "P900"], default="E550W")
    ap.add_argument("--tape", type=int, default=12)
    ap.add_argument("--logo", default=LOGO_DEFAULT,
                    help="logo SVG/PNG, horizontal, black on white (default: zam-bildmarke.svg); "
                         "<name>_<h>.png next to it overrides for that height")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--all", action="store_true", help="render every profile")
    ap.add_argument("--outdir", default="labels")
    ap.add_argument("--preview", help="write a same-scale preview sheet")
    a = ap.parse_args()

    id_ = a.id.upper().replace("-", "")
    _A = "0123456789ABCDEFGHJKMNPRSTUVWXY"
    if len(id_) != 6 or any(c not in _A for c in id_) or \
            sum((i + 1) * _A.index(c) for i, c in enumerate(id_)) % 31:
        sys.exit(f"{a.id}: not a valid label ID (alphabet/length/check symbol)")
    combos = list(PROFILES) if a.all else [(a.printer, a.tape)]
    os.makedirs(a.outdir, exist_ok=True)
    items = []
    for p, t in combos:
        img, info = compose(id_, p, t, a.logo)
        ok = verify(img, id_, PROFILES[(p, t)][2])
        out = a.out if (a.out and not a.all) else os.path.join(a.outdir, f"{id_}_{p}_{t}mm.png")
        img.save(out, dpi=(info["dpi"], info["dpi"]))
        print(f"{'OK ' if ok else 'FAIL'} {out}  {info}")
        items.append((img, info))
    if a.preview:
        preview_sheet(items, a.preview)


if __name__ == "__main__":
    main()
