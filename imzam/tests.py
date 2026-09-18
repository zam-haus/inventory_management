from unittest import TestCase

from .settings import parse_bool


class EnvironmentBooleanTests(TestCase):
    def test_true_values(self):
        for value in ("y", "yes", "t", "true", "on", "1", "TRUE", "Yes"):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), True)

    def test_false_values(self):
        for value in ("n", "no", "f", "false", "off", "0", "FALSE", "Off"):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), False)

    def test_invalid_values_are_rejected(self):
        for value in ("", "invalid", "2", " true "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_bool(value)
