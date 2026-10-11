import io
import tempfile
from unittest import mock
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from PIL import Image

from zamid import core, labels, qr
from zamid.labels import zamlabel
from zamid.models import ZamId


class QrTests(SimpleTestCase):
    def test_random_ids_fit_version_1(self):
        for _ in range(200):
            code = core.generate()
            symbol = qr.make(code)
            self.assertEqual((symbol.version, symbol.mode), (1, "alphanumeric"))
        self.assertIn(b"<svg", qr.svg("K7Q4XD"))


class LabelTests(SimpleTestCase):
    def test_every_profile_matches_the_print_head(self):
        for (printer, tape), (dpi, pins, *_rest) in labels.PROFILES.items():
            with self.subTest(printer=printer, tape=tape):
                image = Image.open(io.BytesIO(labels.render("K7Q4XD", printer, tape)))
                self.assertEqual((image.mode, image.height), ("1", pins))
                self.assertEqual(round(image.info["dpi"][0]), dpi)

    def test_memoized_rendering_is_identical(self):
        uncached = {name: getattr(zamlabel, name).__wrapped__ for name in ("_font", "_cap_height", "vertical_logo")}
        for printer, tape in (("E550W", 12), ("P900", 12)):
            with self.subTest(printer=printer, tape=tape):
                cached = labels.render("K7Q4XD", printer, tape)
                with mock.patch.multiple(zamlabel, **uncached):
                    self.assertEqual(labels.render("K7Q4XD", printer, tape), cached)

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            labels.render("K7Q4XD", "E550W", 36)


class CommandTests(TestCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_generate_labels_check_retire(self):
        shown = self.run_command("zamid_generate", "--count", "3", "--batch", "roll-1").split()
        self.assertEqual(len(shown), 3)
        with tempfile.TemporaryDirectory() as outdir:
            self.run_command("zamid_labels", "--batch", "roll-1", "--printer", "E550W", "--tape", "12", "--outdir", outdir)
            self.assertEqual(len(list(Path(outdir).glob("*_E550W_12mm.png"))), 3)
        self.assertFalse(ZamId.objects.filter(batch="roll-1", printed_at__isnull=True).exists())
        self.assertIn("reserved", self.run_command("zamid_check", shown[0].lower()))
        self.assertIn("invalid (checksum)", self.run_command("zamid_check", "K7Q4XR"))
        self.run_command("zamid_retire", shown[0], "--note", "test")
        self.assertEqual(ZamId.objects.get(pk=shown[0].replace("-", "")).status, "retired")
