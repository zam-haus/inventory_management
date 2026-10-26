"""Text recognition on item photos, for the search (docs/ocr.md); loaded through ocr_util only where photos are
recognized.

Tesseract alone reads a whole photo as a page and turns textures, edges and barcodes into garbage. So a text detection
model (PP-OCRv3, through OpenCV) first finds the lines of text; each is cut out upright, binarized and stacked on a
white page, which Tesseract reads in one go, and words it is unsure about are dropped. EAN barcodes are decoded on
their own and added as "EAN <digits>" lines.
"""
import logging
import os
import re

import cv2
import numpy as np
import pytesseract
from django.conf import settings
from PIL import Image, ImageOps

try:
    from pyzbar import pyzbar
except ImportError:  # zbar library missing (development): OpenCV finds fewer barcodes
    pyzbar = None

logger = logging.getLogger(__name__)

LANG = "deu+eng"
MAX_SIDE = 2000  # photos are scaled down to this many pixels first
DETECTION_SIDE = 1280  # size the detection model sees (a multiple of 32)
LINE_HEIGHT = 64  # each line of text is scaled to this height for Tesseract
MIN_CONFIDENCE = 60  # words Tesseract is less sure about (0 to 100) are dropped
WORD_CHARACTER = re.compile(r"[0-9A-Za-zÄÖÜäöüß]")

_text_detector = None


def recognize(image_path):
    """Text and EAN codes on the photo, one line each; empty if there is none."""
    image = load_image(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    eans = find_eans(gray)
    detector = text_detector()
    if detector:
        lines = read_text_lines(gray, detect_text_lines(detector, image))
    else:
        lines = read_whole_image(gray)
    text = "\n".join(clean_lines(lines) + [f"EAN {code}" for code in eans])
    # remove multiple blank lines and long spaces
    return re.sub(r'[ \t\r\f\v]+\n[ \n\t\r\f\v]+', '\n', re.sub(r'[ \t\r\f\v]+', ' ', text.strip()))


def load_image(image_path):
    """The photo upright as taken (EXIF orientation, which Tesseract ignores), at most MAX_SIDE pixels, as BGR."""
    image = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


# ---------- EAN barcodes ----------

def ean_check_digit_ok(code):
    """EAN-13, EAN-8 or UPC-A (12 digits) with a valid check digit."""
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return False
    if len(code) == 12:
        code = "0" + code
    weights = [3, 1] * 4 if len(code) == 8 else [1, 3] * 6
    total = sum(int(digit) * weight for digit, weight in zip(code[:-1], weights))
    return (10 - total % 10) % 10 == int(code[-1])


def find_eans(gray):
    """EAN codes of the barcodes on the photo, tried at several sizes (zbar misses barcodes too small or too large)."""
    codes = []
    for scale in (1.0, 0.75, 0.5, 0.35):
        image = gray if scale == 1.0 else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        codes += [code for code in decode_barcodes(image) if ean_check_digit_ok(code)]
    return list(dict.fromkeys(codes))


def decode_barcodes(image):
    if pyzbar:
        return [barcode.data.decode() for barcode in pyzbar.decode(image, symbols=[
            pyzbar.ZBarSymbol.EAN13, pyzbar.ZBarSymbol.EAN8, pyzbar.ZBarSymbol.UPCA])]
    try:
        found, codes, _types, _corners = cv2.barcode.BarcodeDetector().detectAndDecodeWithType(image)
    except cv2.error:
        return []
    return list(codes) if found else []


# ---------- text lines ----------

def text_detector():
    """The PP-OCRv3 text detection model (settings.OCR_TEXT_DETECTION_MODEL), loaded once per process; None if it
    is missing (development without the Docker image): then Tesseract reads the whole photo."""
    global _text_detector
    if _text_detector is None:
        path = settings.OCR_TEXT_DETECTION_MODEL
        if not os.path.exists(path):
            logger.warning("Text detection model %s not found: reading whole photos, with more garbage", path)
            _text_detector = False
        else:
            model = cv2.dnn_TextDetectionModel_DB(path)
            # how far the detected text cores are grown into boxes: more takes in parts of the neighbouring lines
            model.setBinaryThreshold(0.3).setPolygonThreshold(0.5).setMaxCandidates(300).setUnclipRatio(1.5)
            # one thread, as Tesseract (OMP_THREAD_LIMIT): leaves the other cores to the app
            cv2.setNumThreads(1)
            _text_detector = model
    return _text_detector


def detect_text_lines(detector, image):
    """Corner points of each line of text, in reading order (top to bottom, left to right)."""
    height, width = image.shape[:2]
    scale = DETECTION_SIDE / max(height, width)
    size = (max(32, round(width * scale / 32) * 32), max(32, round(height * scale / 32) * 32))
    # normalization the model was trained with
    detector.setInputParams(1.0 / 255.0, size, (122.67891434, 116.66876762, 104.00698793), True)
    boxes, _confidences = detector.detect(image)
    boxes = [np.array(box, dtype=np.float32) for box in boxes]
    return sorted(boxes, key=lambda box: (box[:, 1].mean() // 20, box[:, 0].mean()))


def cut_out_line(gray, box, padding=0.15):
    """The line of text in box, its long side horizontal (perhaps upside down), black on white."""
    corners = cv2.boxPoints(cv2.minAreaRect(box))
    first, second = corners[1] - corners[0], corners[2] - corners[1]
    if first[0] * second[1] - first[1] * second[0] < 0:  # walk the corners clockwise
        corners = corners[::-1]
    edges = [np.linalg.norm(corners[(i + 1) % 4] - corners[i]) for i in range(4)]
    # start on a long edge running left to right (vertical text: bottom to top)
    start = max((i for i in range(4) if edges[i] >= edges[(i + 1) % 4]),
                key=lambda i: tuple((corners[(i + 1) % 4] - corners[i]) * (1, -1)))
    source = np.array([corners[(start + k) % 4] for k in range(4)], dtype=np.float32)
    length, height = edges[start], edges[(start + 1) % 4]
    pad = padding * height
    target = np.array([[pad, pad], [pad + length, pad], [pad + length, pad + height], [pad, pad + height]],
                      dtype=np.float32)
    line = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(source, target),
                               (max(1, int(length + 2 * pad)), max(1, int(height + 2 * pad))),
                               flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if min(line.shape) < 6:
        return None
    line = cv2.resize(line, (max(1, line.shape[1] * LINE_HEIGHT // line.shape[0]), LINE_HEIGHT),
                      interpolation=cv2.INTER_CUBIC)
    _, line = cv2.threshold(line, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.concatenate([line[0], line[-1], line[:, 0], line[:, -1]]).mean() < 128:  # light text on dark
        line = 255 - line
    return line[:, :4000]


def read_text_lines(gray, boxes):
    """Tesseract reads all lines stacked on one page (one call instead of one per line); the page is read upright
    and upside down, and the more confident reading wins."""
    lines = [line for line in (cut_out_line(gray, box) for box in boxes) if line is not None]
    if not lines:
        return []
    gap = LINE_HEIGHT // 2
    page = np.full((len(lines) * (LINE_HEIGHT + gap) + gap, max(line.shape[1] for line in lines) + 2 * LINE_HEIGHT),
                   255, dtype=np.uint8)
    for i, line in enumerate(lines):
        top = gap + i * (LINE_HEIGHT + gap)
        page[top:top + LINE_HEIGHT, LINE_HEIGHT:LINE_HEIGHT + line.shape[1]] = line
    readings = [tesseract_words(image, "--psm 4") for image in (page, cv2.rotate(page, cv2.ROTATE_180))]
    return max(readings, key=lambda words: mean_confidence(words) * len(words) ** 0.25 if words else 0)


def read_whole_image(gray):
    """Without the detection model: the whole photo, with Sauvola binarization (best without text lines)."""
    return tesseract_words(gray, "--psm 3 -c thresholding_method=2")


def tesseract_words(image, config):
    """Lines of (word, confidence)."""
    data = pytesseract.image_to_data(image, lang=LANG, config=config, output_type=pytesseract.Output.DICT)
    lines = {}
    for i, word in enumerate(data["text"]):
        if word.strip():
            line = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(line, []).append((word.strip(), float(data["conf"][i])))
    return [lines[line] for line in sorted(lines)]


def mean_confidence(lines):
    confidences = [confidence for line in lines for _, confidence in line if confidence >= 0]
    return sum(confidences) / len(confidences) if confidences else 0


def clean_lines(lines):
    """Lines without uncertain words and without symbol-only garbage."""
    cleaned = []
    for line in lines:
        words = [word for word, confidence in line if confidence >= MIN_CONFIDENCE and WORD_CHARACTER.search(word)]
        text = " ".join(words)
        letters_and_digits = sum(character.isalnum() for character in text)
        if (letters_and_digits >= 2 and letters_and_digits >= 0.6 * len(text.replace(" ", ""))
                and any(len(word) > 1 for word in words)):
            cleaned.append(text)
    return cleaned
