"""Turns an uploaded floor plan (PDF, PNG, JPEG, WebP or SVG) into the image the map shows.

PDFs are rendered with poppler's pdftoppm, without annotations (notes and stamps someone added in a viewer can
name people). Raster images are cropped to the drawing and made smaller when needed; the result is WebP without
metadata. The crop is an outline: outside it the image is transparent; so is the white paper if wanted.
SVGs are kept as they are (served with a sandbox, views.plan_image).
"""
import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _, gettext_lazy
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageOps

# Longest side of a rendered plan (an A0 sheet at 300 dpi is 14 000 pixels); browsers get it in tiles (plans.py).
MAX_SIDE = 16000
# Longest side of the preview image and of each tile: phones decode images of this size quickly.
TILE_SIDE = 2048
# Tiles reach this far into their neighbours, so that no hairline gap shows between them on the map.
TILE_OVERLAP = 2
PDF_TIMEOUT = 90
RASTER = {".png", ".jpg", ".jpeg", ".webp"}
# Plans can be large; Pillow's default limit is meant for untrusted photos of unknown size.
Image.MAX_IMAGE_PIXELS = 400_000_000


class RenderError(ValueError):
    pass


def pdftoppm():
    return shutil.which("pdftoppm")


def _render_pdf(path, page, dpi):
    command = pdftoppm()
    if command is None:
        raise RenderError(_("PDF plans need poppler (pdftoppm) on the server; see docs/maps.md."))
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "page"
        try:
            subprocess.run([command, "-hide-annotations", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png",
                            "-singlefile", str(path), str(out)], check=True, capture_output=True, timeout=PDF_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise RenderError(_("Rendering the PDF took too long; try a lower resolution.")) from error
        except subprocess.CalledProcessError as error:
            raise RenderError(_("The PDF could not be rendered: %(error)s") % {
                "error": error.stderr.decode(errors="replace").strip()[:300]}) from error
        with Image.open(out.with_suffix(".png")) as image:
            image.load()
            return image.copy()


CROP_FORMAT = gettext_lazy("The crop is an outline of at least three corners [[x, y], …], or [left, top, right, bottom], as "
                "fractions of the page's width and height, e.g. [[0.05, 0.1], [0.7, 0.1], [0.7, 0.95]].")


def crop_polygon(crop):
    """The outline of a crop, [[x, y], …] as fractions of the page, None for the whole page (also for an empty crop),
    else RenderError. A rectangle [left, top, right, bottom] (older crops) becomes its four corners."""
    if crop in (None, "", [], {}):
        return None
    if isinstance(crop, (str, bytes, dict)) or not hasattr(crop, "__iter__"):
        raise RenderError(str(CROP_FORMAT))
    crop = list(crop)
    try:
        if all(isinstance(value, (int, float)) for value in crop):
            if len(crop) != 4:
                raise RenderError(str(CROP_FORMAT))
            left, top, right, bottom = (float(value) for value in crop)
            if not (left < right and top < bottom):
                raise RenderError(_("The crop must lie within the page (fractions from 0 to 1, left before right)."))
            points = [[left, top], [right, top], [right, bottom], [left, bottom]]
        else:
            points = [[float(x), float(y)] for x, y in crop]
    except (TypeError, ValueError) as error:
        raise RenderError(str(CROP_FORMAT)) from error
    if len(points) < 3:
        raise RenderError(str(CROP_FORMAT))
    if not all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points):
        raise RenderError(_("The crop must lie within the page (fractions from 0 to 1, left before right)."))
    area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])) / 2
    if abs(area) < 1e-6:
        raise RenderError(_("The crop encloses no area."))
    return [[round(x, 6), round(y, 6)] for x, y in points]


def crop_bounds(crop):
    """[left, top, right, bottom] around a crop (fractions of the page), [0, 0, 1, 1] for the whole page."""
    try:
        polygon = crop_polygon(crop)
    except RenderError:
        polygon = None
    if not polygon:
        return [0.0, 0.0, 1.0, 1.0]
    xs, ys = zip(*polygon)
    return [min(xs), min(ys), max(xs), max(ys)]


def _is_rectangle(polygon):
    left, top, right, bottom = crop_bounds(polygon)
    return len(polygon) == 4 and all(x in (left, right) and y in (top, bottom) for x, y in polygon)


def crop_image(image, polygon):
    """The part of the image inside the outline: cut to its bounds, transparent outside it."""
    width, height = image.size
    left, top, right, bottom = crop_bounds(polygon)
    box = (int(left * width), int(top * height), min(width, int(-(-right * width // 1))),
           min(height, int(-(-bottom * height // 1))))
    image = image.crop(box)
    if _is_rectangle(polygon):
        return image
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon([(x * width - box[0], y * height - box[1]) for x, y in polygon], fill=255)
    image = image.convert("RGBA")
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def white_to_alpha(image):
    """The paper made transparent: white becomes transparent, light grey half so, lines keep their colour
    (colour to alpha, as in image editors)."""
    rgba = np.asarray(image.convert("RGBA"))
    darkness = 255 - rgba[..., :3].min(axis=2)  # how far the most coloured channel is from white
    alpha = darkness.astype(np.float32) / 255
    out = np.empty_like(rgba)
    safe = np.maximum(alpha, 1 / 255)
    for channel in range(3):
        value = 255 - (255 - rgba[..., channel].astype(np.float32)) / safe
        out[..., channel] = np.clip(value, 0, 255).astype(np.uint8)
    out[..., 3] = (alpha * rgba[..., 3]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _svg_size(data):
    """(width, height) of an SVG from its viewBox (else its width and height), as pixels of the image."""
    head = data[:4096].decode("utf-8", errors="replace")
    root = re.search(r"<svg\b[^>]*>", head, re.S)
    if not root:
        raise RenderError(_("This is not an SVG file."))
    tag = root.group(0)
    if box := re.search(r'viewBox\s*=\s*["\']\s*[-\d.e]+[\s,]+[-\d.e]+[\s,]+([\d.e]+)[\s,]+([\d.e]+)', tag):
        return float(box.group(1)), float(box.group(2))
    width = re.search(r'\bwidth\s*=\s*["\']([\d.]+)', tag)
    height = re.search(r'\bheight\s*=\s*["\']([\d.]+)', tag)
    if width and height:
        return float(width.group(1)), float(height.group(1))
    raise RenderError(_("The SVG has neither a viewBox nor a width and height."))


def render(source, *, suffix, page=1, dpi=150, crop=None, transparent=False):
    """(image, width, height) of a plan file: a Pillow image (cropped, without paper if `transparent`, at most
    MAX_SIDE), or for an SVG a ContentFile of it as it is. `source` is a path or a file object; `crop` an outline
    (crop_polygon)."""
    suffix = suffix.lower()
    polygon = crop_polygon(crop)
    if suffix == ".svg":
        if polygon:
            raise RenderError(_("SVG plans cannot be cropped here; crop them before uploading."))
        data = Path(source).read_bytes() if isinstance(source, (str, Path)) else source.read()
        width, height = _svg_size(data)
        return ContentFile(data, name="plan.svg"), width, height
    if suffix == ".pdf":
        if isinstance(source, (str, Path)):
            image = _render_pdf(source, page, dpi)
        else:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as copy:
                shutil.copyfileobj(source, copy)
                copy.flush()
                image = _render_pdf(copy.name, page, dpi)
    elif suffix in RASTER:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
    else:
        raise RenderError(_("Floor plans can be PDF, PNG, JPEG, WebP or SVG files. Convert DWG files first "
                            "(docs/maps.md)."))
    if polygon:
        image = crop_image(image, polygon)
    if transparent:
        image = white_to_alpha(image)
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image, image.width, image.height


def webp(image, name):
    """A ContentFile of the image as WebP, without metadata."""
    out = io.BytesIO()
    image.save(out, "WEBP", quality=90, method=4)
    return ContentFile(out.getvalue(), name=name)


def preview(image, side=TILE_SIDE, name="plan.webp"):
    """The plan made small (TILE_SIDE), e.g. for the plans list."""
    small = image.copy()
    small.thumbnail((side, side), Image.Resampling.LANCZOS)
    return webp(small, name)


def tiles(image):
    """[(x, y, ContentFile)] of the image cut in tiles of TILE_SIDE (plus TILE_OVERLAP into the next), row by row."""
    width, height = image.size
    result = []
    for y in range(0, height, TILE_SIDE):
        for x in range(0, width, TILE_SIDE):
            box = (x, y, min(x + TILE_SIDE + TILE_OVERLAP, width), min(y + TILE_SIDE + TILE_OVERLAP, height))
            result.append((x, y, webp(image.crop(box), f"tile-{x}-{y}.webp")))
    return result
