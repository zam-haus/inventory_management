import io
import tempfile
from unittest import mock
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from inventory.label_ids import core, labels, parsing, qr
from inventory.label_ids.labels import idlabel
from inventory.models import LabelId


PRODUCTION = override_settings(LABEL_ID_BASE_URL="https://i.zam.haus/")
LOCAL = override_settings(LABEL_ID_BASE_URL="http://i.localhost:8000")


@PRODUCTION
class QrTests(SimpleTestCase):
    def test_random_ids_fit_version_1(self):
        for _ in range(200):
            code = core.generate()
            symbol = qr.make(code)
            self.assertEqual((symbol.version, symbol.mode), (1, "alphanumeric"))
        self.assertIn(b"<svg", qr.svg("K7R4XD"))
        self.assertEqual(qr.url_prefix(), "HTTPS://I.ZAM.HAUS/")


@LOCAL
class LocalBaseUrlTests(SimpleTestCase):
    def test_qr_uses_the_local_base_and_grows(self):
        symbol = qr.make("K7R4XD")
        self.assertEqual((symbol.version, symbol.mode), (2, "alphanumeric"))
        self.assertEqual(qr.url_prefix(), "HTTP://I.LOCALHOST:8000/")

    def test_labels_still_fit_and_decode(self):
        for (printer, tape), (_dpi, pins, module_dots, *_rest) in labels.PROFILES.items():
            with self.subTest(printer=printer, tape=tape):
                image = Image.open(io.BytesIO(labels.render("K7R4XD", printer, tape)))
                self.assertEqual(image.height, pins)
                with mock.patch.object(idlabel, "URL_PREFIX", "HTTP://I.LOCALHOST:8000/"):
                    self.assertTrue(idlabel.verify(image.convert("1"), "K7R4XD", module_dots))  # needs OpenCV
        self.assertEqual(idlabel.URL_PREFIX, "HTTPS://I.ZAM.HAUS/")

    def test_scanned_local_urls_are_accepted(self):
        for raw in ("HTTP://I.LOCALHOST:8000/K7R4XD", "http://i.localhost:8000/k7r-4xd/"):
            self.assertEqual(parsing.code_from_scan(raw), "K7R4XD")


@PRODUCTION
class LabelTests(SimpleTestCase):
    def test_every_profile_matches_the_print_head(self):
        for (printer, tape), (dpi, pins, *_rest) in labels.PROFILES.items():
            with self.subTest(printer=printer, tape=tape):
                image = Image.open(io.BytesIO(labels.render("K7R4XD", printer, tape)))
                self.assertEqual((image.mode, image.height), ("1", pins))
                self.assertEqual(round(image.info["dpi"][0]), dpi)

    def test_memoized_rendering_is_identical(self):
        uncached = {name: getattr(idlabel, name).__wrapped__ for name in ("_font", "_cap_height", "vertical_logo")}
        for printer, tape in (("E550W", 12), ("P900", 12)):
            with self.subTest(printer=printer, tape=tape):
                cached = labels.render("K7R4XD", printer, tape)
                with mock.patch.multiple(idlabel, **uncached):
                    self.assertEqual(labels.render("K7R4XD", printer, tape), cached)

    def test_logo_text_is_the_configured_name(self):
        default = labels.render("K7R4XD", "P900", 24)
        with override_settings(LABEL_ID_NAME="ACMEid"):
            self.assertNotEqual(labels.render("K7R4XD", "P900", 24), default)
        self.assertEqual(labels.render("K7R4XD", "P900", 24), default)
        self.assertEqual(idlabel.LOGO_TEXT, "ZAMid")

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            labels.render("K7R4XD", "E550W", 36)


@PRODUCTION
class CommandTests(TestCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_generate_labels_check_retire(self):
        shown = self.run_command("label_id_generate", "--count", "3", "--batch", "roll-1").split()
        self.assertEqual(len(shown), 3)
        with tempfile.TemporaryDirectory() as outdir:
            self.run_command("label_id_labels", "--batch", "roll-1", "--printer", "E550W", "--tape", "12", "--outdir", outdir)
            self.assertEqual(len(list(Path(outdir).glob("*_E550W_12mm.png"))), 3)
        self.assertFalse(LabelId.objects.filter(batch="roll-1", printed_at__isnull=True).exists())
        self.assertIn("reserved", self.run_command("label_id_check", shown[0].lower()))
        self.assertIn("invalid (checksum)", self.run_command("label_id_check", "K7R4XR"))
        self.run_command("label_id_retire", shown[0], "--note", "test")
        self.assertEqual(LabelId.objects.get(pk=shown[0].replace("-", "")).status, "retired")
