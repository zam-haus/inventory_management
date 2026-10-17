from django.template import Context, Template
from django.test import SimpleTestCase

from ..icons import ICON_DIR, icon


class IconTests(SimpleTestCase):
    def test_icons_are_inline_hidden_and_sized_like_text(self):
        svg = icon("camera")
        self.assertTrue(svg.startswith('<svg aria-hidden="true" focusable="false"'))
        self.assertIn('width="1em" height="1em"', svg)
        self.assertIn('class="bi bi-camera"', svg)
        self.assertIn('class="bi bi-sort-up text-danger"', icon("sort-up", "text-danger"))

    def test_template_tag_renders_unescaped_and_can_be_passed_on(self):
        rendered = Template('{% load icons actions %}{% icon "trash3" %}'
                            '{% icon "archive" as remove %}{% disabled_action remove name="Remove" %}').render(
            Context({"user": type("User", (), {"is_authenticated": True})()}))
        self.assertIn('class="bi bi-trash3"', rendered)
        self.assertIn('disabled aria-hidden="true"><svg aria-hidden="true"', rendered)  # inside the disabled button
        self.assertIn('class="bi bi-archive"', rendered)
        self.assertNotIn("&lt;svg", rendered)

    def test_unknown_icons_fail_loudly(self):
        with self.assertRaisesMessage(ValueError, ICON_DIR):
            icon("does-not-exist")

    def test_icons_used_in_templates_are_vendored(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        names = set()
        for path in [*root.glob("inventory/templates/**/*.html"), *root.glob("templates/**/*.html")]:
            names |= set(re.findall(r'\{% icon "([a-z0-9-]+)"', path.read_text(encoding="utf-8")))
        self.assertTrue(names)
        for name in sorted(names):
            with self.subTest(name):
                icon(name)
