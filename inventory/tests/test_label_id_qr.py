import io

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from inventory.label_ids import core, parsing, qr
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

    def test_scanned_local_urls_are_accepted(self):
        for raw in ("HTTP://I.LOCALHOST:8000/K7R4XD", "http://i.localhost:8000/k7r-4xd/"):
            self.assertEqual(parsing.code_from_scan(raw), "K7R4XD")


@PRODUCTION
class CommandTests(TestCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_generate_labels_check_retire(self):
        shown = self.run_command("label_id_generate", "--count", "3", "--batch", "roll-1").split()
        self.assertEqual(len(shown), 3)
        self.assertIn("reserved", self.run_command("label_id_check", shown[0].lower()))
        self.assertIn("invalid (checksum)", self.run_command("label_id_check", "K7R4XR"))
        self.run_command("label_id_retire", shown[0], "--note", "test")
        self.assertEqual(LabelId.objects.get(pk=shown[0].replace("-", "")).status, "retired")
