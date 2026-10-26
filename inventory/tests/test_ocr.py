import io
import os
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from PIL import Image, ImageDraw

from .. import ocr_util, text_recognition

L_CODES = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean13_image(code, module=4, height=120):
    """A printed EAN-13 barcode on white, as on a label."""
    right = ["".join("1" if bit == "0" else "0" for bit in L_CODES[int(digit)]) for digit in code[7:]]
    left = [L_CODES[int(digit)] if parity == "L" else "".join(reversed(
        "".join("1" if bit == "0" else "0" for bit in L_CODES[int(digit)])))
        for digit, parity in zip(code[1:7], PARITY[int(code[0])])]
    bits = "101" + "".join(left) + "01010" + "".join(right) + "101"
    quiet = 12 * module
    image = Image.new("L", (len(bits) * module + 2 * quiet, height + 2 * quiet), 255)
    draw = ImageDraw.Draw(image)
    for i, bit in enumerate(bits):
        if bit == "1":
            draw.rectangle([quiet + i * module, quiet, quiet + (i + 1) * module - 1, quiet + height], fill=0)
    return image


def tesseract_data(*lines):
    """pytesseract.image_to_data output for lines of (word, confidence)."""
    data = {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []}
    for number, line in enumerate(lines, 1):
        for word, confidence in line:
            data["text"].append(word)
            data["conf"].append(confidence)
            data["block_num"].append(1)
            data["par_num"].append(1)
            data["line_num"].append(number)
    return data


class OcrLoadingTests(SimpleTestCase):
    def test_django_processes_do_not_load_opencv(self):
        """Gunicorn and the Celery workers import ocr_util through the models; only recognizing a photo loads OpenCV
        (about 60 MB more per process)."""
        code = ("import sys, django; django.setup(); import inventory.models, inventory.tasks; "
                "print('cv2' in sys.modules, 'pyzbar' in sys.modules)")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                cwd=settings.BASE_DIR, env={**os.environ, "DJANGO_SETTINGS_MODULE": "imzam.settings"})
        self.assertEqual(result.stdout.split(), ["False", "False"])


class OcrTests(SimpleTestCase):
    def setUp(self):
        patcher = patch.object(text_recognition, "_text_detector", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uncertain_words_and_symbol_lines_are_dropped(self):
        lines = [[("Senkkopfschrauben", 91), ("TX10", 88), ("ii", 12)],
                 [("|", 70), ("=", 80), ("»", 75)],
                 [("a", 90), ("e", 90)],
                 [("3,0x16", 85)]]
        self.assertEqual(text_recognition.clean_lines(lines), ["Senkkopfschrauben TX10", "3,0x16"])

    def test_photo_is_turned_as_taken(self):
        content = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6  # taken with the camera turned: the viewer rotates by 90°
        Image.new("RGB", (40, 20), "white").save(content, "JPEG", exif=exif)
        content.seek(0)
        self.assertEqual(text_recognition.load_image(content).shape[:2], (40, 20))

    def test_vertical_text_line_is_cut_out_lying(self):
        gray = np.full((400, 200), 255, dtype=np.uint8)
        gray[50:350, 80:120] = 0
        box = np.array([[80, 350], [80, 50], [120, 50], [120, 350]], dtype=np.float32)
        line = text_recognition.cut_out_line(gray, box)
        self.assertEqual(line.shape[0], text_recognition.LINE_HEIGHT)
        self.assertGreater(line.shape[1], 4 * text_recognition.LINE_HEIGHT)

    def test_ean_check_digit(self):
        self.assertTrue(text_recognition.ean_check_digit_ok("4006381333931"))
        self.assertFalse(text_recognition.ean_check_digit_ok("4006381333932"))
        self.assertTrue(text_recognition.ean_check_digit_ok("96385074"))  # EAN-8
        self.assertTrue(text_recognition.ean_check_digit_ok("036000291452"))  # UPC-A
        self.assertFalse(text_recognition.ean_check_digit_ok("40063813339"))

    def test_ean_barcode_is_decoded(self):
        gray = np.asarray(ean13_image("4006381333931"))
        self.assertEqual(text_recognition.find_eans(gray), ["4006381333931"])

    @override_settings(OCR_TEXT_DETECTION_MODEL="/nonexistent/model.onnx")
    def test_without_detection_model_tesseract_reads_the_whole_photo(self):
        content = io.BytesIO()
        ean13_image("4006381333931").convert("RGB").save(content, "PNG")
        content.seek(0)
        data = tesseract_data([("Kistengriff", 93), ("verzinkt", 90)], [("~", 30), ("ee", 20)])
        with patch.object(text_recognition.pytesseract, "image_to_data", return_value=data) as tesseract, \
                self.assertLogs("inventory.text_recognition", "WARNING"):
            text = ocr_util.ocr_on_image_path(content)
        self.assertEqual(text, "Kistengriff verzinkt\nEAN 4006381333931")
        self.assertIn("thresholding_method=2", tesseract.call_args.kwargs["config"])

    def test_more_confident_reading_of_the_lines_wins(self):
        upright = [[("Rpew", 30)]]
        upside_down = [[("Schraube", 92), ("M6", 90)]]
        gray = np.full((100, 300), 255, dtype=np.uint8)
        box = np.array([[20, 70], [20, 30], [280, 30], [280, 70]], dtype=np.float32)
        with patch.object(text_recognition, "tesseract_words", side_effect=[upright, upside_down]):
            self.assertEqual(text_recognition.read_text_lines(gray, [box]), upside_down)
