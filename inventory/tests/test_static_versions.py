import os
import tempfile
from pathlib import Path

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import SimpleTestCase, override_settings


class StaticVersionTests(SimpleTestCase):
    def test_url_changes_with_the_file(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(STATICFILES_DIRS=[folder]):
            finders.get_finder.cache_clear()
            try:
                css = Path(folder, "versioned-test.css")
                css.write_text("a { color: red; }")
                first = static("versioned-test.css")
                self.assertRegex(first, r"^/static/versioned-test\.css\?v=[0-9a-f]{10}$")
                self.assertEqual(static("versioned-test.css"), first)  # stable while unchanged
                css.write_text("a { color: blue; }")
                stat = css.stat()
                os.utime(css, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
                self.assertNotEqual(static("versioned-test.css"), first)
            finally:
                finders.get_finder.cache_clear()

    def test_unknown_files_keep_their_plain_url(self):
        self.assertEqual(static("does/not/exist.css"), "/static/does/not/exist.css")
