import random
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from inventory.zamid import core, parsing
from inventory.zamid.fields import ZamIdFormField, ZamIdInput

VECTORS = [
    ("00000", "000000", "000-000"),
    ("00001", "00001S", "000-01S"),
    ("10000", "100005", "100-005"),
    ("12345", "12345V", "123-45V"),
    ("ABCDE", "ABCDEM", "ABC-DEM"),
    ("K7Q4X", "K7Q4XD", "K7Q-4XD"),
    ("5S8B2", "5S8B2E", "5S8-B2E"),
    ("YYYYY", "YYYYYJ", "YYY-YYJ"),
]


class CoreTests(SimpleTestCase):
    def test_vectors(self):
        for payload, canonical, shown in VECTORS:
            with self.subTest(payload):
                self.assertEqual(payload + core.check_symbol(payload), canonical)
                self.assertTrue(core.is_valid(canonical))
                self.assertEqual(core.display(canonical), shown)

    def test_alphabet_excludes_confusable_letters(self):
        self.assertEqual(len(core.ALPHABET), 31)
        for letter in "ILOUZ":
            self.assertNotIn(letter, core.ALPHABET)

    def test_normalize_accepts_display_forms(self):
        for raw in ("k7q-4xd", " K7Q 4XD ", "K7Q_4XD", "K7Q.4XD", "K7Q4XD"):
            with self.subTest(raw):
                self.assertEqual(core.normalize(raw), "K7Q4XD")

    def test_normalize_maps_lookalikes(self):
        for lookalike, real in [("O", "0"), ("I", "1"), ("L", "1"), ("Z", "Y"), ("U", "V")]:
            payload = real + "ABCD"
            canonical = payload + core.check_symbol(payload)
            with self.subTest(lookalike):
                self.assertEqual(core.normalize(lookalike + canonical[1:]), canonical)
                self.assertEqual(core.normalize(lookalike.lower() + canonical[1:].lower()), canonical)

    def test_malformed(self):
        for raw in ("K7Q4X", "K7Q4XDD", "K7Q4X!", "", "   ", "ÄÖÜ123"):
            with self.subTest(raw), self.assertRaises(core.InvalidZamId) as caught:
                core.normalize(raw)
            self.assertEqual(caught.exception.args[0], "malformed")

    def test_checksum(self):
        with self.assertRaises(core.InvalidZamId) as caught:
            core.normalize("K7Q4XR")
        self.assertEqual(caught.exception.args[0], "checksum")

    def test_every_substitution_and_swap_is_detected(self):
        rng = random.Random(2026)
        for _ in range(10_000):
            payload = "".join(rng.choice(core.ALPHABET) for _ in range(core.PAYLOAD_LEN))
            cid = payload + core.check_symbol(payload)
            self.assertTrue(core.is_valid(cid))
            i = rng.randrange(core.ID_LEN)
            c = rng.choice(core.ALPHABET.replace(cid[i], ""))
            self.assertFalse(core.is_valid(cid[:i] + c + cid[i + 1:]))
            i, j = rng.sample(range(core.ID_LEN), 2)
            if cid[i] != cid[j]:
                swapped = list(cid)
                swapped[i], swapped[j] = swapped[j], swapped[i]
                self.assertFalse(core.is_valid("".join(swapped)))

    def test_exhaustive_errors_for_sample(self):
        rng = random.Random(31)
        for _ in range(300):
            payload = "".join(rng.choice(core.ALPHABET) for _ in range(core.PAYLOAD_LEN))
            cid = payload + core.check_symbol(payload)
            for i in range(core.ID_LEN):
                for c in core.ALPHABET:
                    if c != cid[i]:
                        self.assertFalse(core.is_valid(cid[:i] + c + cid[i + 1:]))
                for j in range(i + 1, core.ID_LEN):
                    if cid[i] != cid[j]:
                        s = list(cid)
                        s[i], s[j] = s[j], s[i]
                        self.assertFalse(core.is_valid("".join(s)))

    def test_generate_skips_reserved(self):
        with mock.patch("inventory.zamid.core.secrets.choice", side_effect=list("00000K7Q4X")):
            self.assertEqual(core.generate(), "K7Q4XD")
        for _ in range(1000):
            cid = core.generate()
            self.assertTrue(core.is_valid(cid))
            self.assertNotIn(cid, core.RESERVED)

    def test_suggestions(self):
        self.assertIn("K7Q4XD", core.suggestions("K7Q4XR"))
        self.assertIn("K7Q4XD", core.suggestions("K7Q-X4D"))  # swapped
        self.assertEqual(core.suggestions("K7Q4"), [])


class ParsingTests(SimpleTestCase):
    def test_scanned_urls(self):
        for raw in ("HTTPS://I.ZAM.HAUS/K7Q4XD", "https://id.zam.haus/k7q-4xd", "https://inv.zam.haus/id/K7Q4XD/",
                    "i.zam.haus/K7Q4XD", " K7Q-4XD\n"):
            with self.subTest(raw):
                self.assertEqual(parsing.code_from_scan(raw), "K7Q4XD")

    def test_other_urls_are_malformed(self):
        with self.assertRaises(core.InvalidZamId):
            parsing.code_from_scan("https://example.com/K7Q4XD")


class FieldTests(SimpleTestCase):
    def test_form_field(self):
        field = ZamIdFormField()
        self.assertEqual(field.clean("k7q-4xd"), "K7Q4XD")
        self.assertEqual(field.clean("HTTPS://I.ZAM.HAUS/K7Q4XD"), "K7Q4XD")
        for raw, reason in (("K7Q4XR", "checksum"), ("nope", "malformed")):
            with self.subTest(raw), self.assertRaises(ValidationError) as caught:
                field.clean(raw)
            self.assertEqual(caught.exception.code, reason)

    def test_widget_shows_display_form(self):
        self.assertEqual(ZamIdInput().format_value("K7Q4XD"), "K7Q-4XD")
        self.assertEqual(ZamIdInput().format_value("typo"), "typo")
