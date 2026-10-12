from django.test import SimpleTestCase

from ..templatetags.mytemplatetags import markdown, markdown_plain


class MarkdownTests(SimpleTestCase):
    def test_links_and_lists(self):
        html = markdown("[Manual](https://example.org/manual.pdf)\n\n- one\n- two")
        self.assertInHTML('<a href="https://example.org/manual.pdf" rel="nofollow noopener noreferrer">Manual</a>', html)
        self.assertInHTML("<ul><li>one</li><li>two</li></ul>", html)

    def test_line_breaks_of_plain_descriptions_stay(self):
        self.assertInHTML("<p>Steel<br>M4 x 20</p>", markdown("Steel\nM4 x 20"))

    def test_unsafe_html_is_removed(self):
        html = markdown('<script>alert(1)</script><a href="/x" onclick="steal()">x</a> [y](javascript:alert(2)) '
                        '<img src=x onerror=alert(3)>')
        for unsafe in ("<script", "alert(1)", "onclick", "javascript:", "<img", "onerror"):
            self.assertNotIn(unsafe, html)

    def test_text_is_escaped(self):
        self.assertInHTML("<p>a &amp; b &lt; c</p>", markdown("a & b < c"))

    def test_plain_preview(self):
        self.assertEqual(markdown_plain("# Head\nsome **bold** [link](https://example.org)"), "Head some bold link")
        self.assertEqual(markdown_plain(""), "")
