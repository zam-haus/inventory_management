import random
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from inventory.label_ids import core, parsing
from inventory.label_ids.fields import LabelIdFormField, LabelIdInput

VECTORS = [
    ("00000", "000000", "000-000"),
    ("00001", "00001T", "000-01T"),
    ("10000", "100005", "100-005"),
    ("12345", "12345V", "123-45V"),
    ("ABCDE", "ABCDEM", "ABC-DEM"),
    ("K7R4X", "K7R4XD", "K7R-4XD"),
    ("5S8B2", "5S8B24", "5S8-B24"),
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
        for letter in "ILOQZ":
            self.assertNotIn(letter, core.ALPHABET)

    def test_normalize_accepts_display_forms(self):
        for raw in ("k7r-4xd", " K7R 4XD ", "K7R_4XD", "K7R.4XD", "K7R4XD"):
            with self.subTest(raw):
                self.assertEqual(core.normalize(raw), "K7R4XD")

    def test_normalize_maps_lookalikes(self):
        for lookalike, real in [("O", "0"), ("Q", "0"), ("I", "1"), ("L", "1"), ("Z", "Y")]:
            payload = real + "ABCD"
            canonical = payload + core.check_symbol(payload)
            with self.subTest(lookalike):
                self.assertEqual(core.normalize(lookalike + canonical[1:]), canonical)
                self.assertEqual(core.normalize(lookalike.lower() + canonical[1:].lower()), canonical)

    def test_u_and_v_are_distinct_symbols(self):
        self.assertEqual(core.normalize("K7U-4XV"), "K7U4XV")
        with self.assertRaises(core.InvalidLabelId) as caught:
            core.normalize("K7V4XV")
        self.assertEqual(caught.exception.args[0], "checksum")

    def test_malformed(self):
        for raw in ("K7R4X", "K7R4XDD", "K7R4X!", "", "   ", "ÄÖÜ123"):
            with self.subTest(raw), self.assertRaises(core.InvalidLabelId) as caught:
                core.normalize(raw)
            self.assertEqual(caught.exception.args[0], "malformed")

    def test_checksum(self):
        with self.assertRaises(core.InvalidLabelId) as caught:
            core.normalize("K7R4XR")
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
        with mock.patch("inventory.label_ids.core.secrets.choice", side_effect=list("00000K7R4X")):
            self.assertEqual(core.generate(), "K7R4XD")
        for _ in range(1000):
            cid = core.generate()
            self.assertTrue(core.is_valid(cid))
            self.assertNotIn(cid, core.RESERVED)

    def test_suggestions(self):
        self.assertIn("K7R4XD", core.suggestions("K7R4XR"))
        self.assertIn("K7R4XD", core.suggestions("K7R-X4D"))  # swapped
        self.assertEqual(core.suggestions("K7R4"), [])


class ParsingTests(SimpleTestCase):
    def test_scanned_urls(self):
        for raw in ("HTTPS://I.ZAM.HAUS/K7R4XD", "https://id.zam.haus/k7r-4xd", "https://inv.zam.haus/id/K7R4XD/",
                    "i.zam.haus/K7R4XD", " K7R-4XD\n"):
            with self.subTest(raw):
                self.assertEqual(parsing.code_from_scan(raw), "K7R4XD")

    @override_settings(LABEL_ID_RESOLVER_HOSTS=["l.acme.example"], LABEL_ID_BASE_URL="https://l.acme.example/",
                       LABEL_ID_INVENTORY_BASE="https://stuff.acme.example", DEFAULT_URL="https://stuff.acme.example")
    def test_hosts_come_from_the_settings(self):
        for raw in ("HTTPS://L.ACME.EXAMPLE/K7R4XD", "https://stuff.acme.example/id/k7r-4xd"):
            self.assertEqual(parsing.code_from_scan(raw), "K7R4XD")
        with self.assertRaises(core.InvalidLabelId):
            parsing.code_from_scan("https://i.zam.haus/K7R4XD")

    def test_other_urls_are_malformed(self):
        with self.assertRaises(core.InvalidLabelId):
            parsing.code_from_scan("https://example.com/K7R4XD")


class FieldTests(SimpleTestCase):
    def test_form_field(self):
        field = LabelIdFormField()
        self.assertEqual(field.clean("k7r-4xd"), "K7R4XD")
        self.assertEqual(field.clean("HTTPS://I.ZAM.HAUS/K7R4XD"), "K7R4XD")
        for raw, reason in (("K7R4XR", "checksum"), ("nope", "malformed")):
            with self.subTest(raw), self.assertRaises(ValidationError) as caught:
                field.clean(raw)
            self.assertEqual(caught.exception.code, reason)

    def test_widget_shows_display_form(self):
        self.assertEqual(LabelIdInput().format_value("K7R4XD"), "K7R-4XD")
        self.assertEqual(LabelIdInput().format_value("typo"), "typo")
