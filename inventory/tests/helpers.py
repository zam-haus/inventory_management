"""Shared by several test modules."""
import re
from html.parser import HTMLParser


def without_change_log(response):
    """The page without its change log, which names deleted items and locations as history."""
    return re.sub(r'<section [^>]*class="\w+-panel change-log".*?</section>', "", response.content.decode(), flags=re.S)


def breadcrumbs(response):
    """The rows of the page's breadcrumbs (base.html), each a list of (link, text, current) from the top down;
    the link is None for the page itself where it is no link."""
    class Crumbs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows, self.depth, self.crumb = [], 0, None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "data-page-breadcrumbs" in attrs:
                self.depth = 1
            elif self.depth:
                self.depth += tag != "svg" and tag not in ("path", "circle", "rect")
                if tag == "nav":
                    self.rows.append([])
                elif self.crumb is None and (tag == "a" or "aria-current" in attrs) and self.rows:
                    self.crumb = [attrs.get("href"), "", "aria-current" in attrs, self.depth]

        def handle_endtag(self, tag):
            if not self.depth or tag in ("svg", "path", "circle", "rect"):
                return
            if self.crumb and self.depth == self.crumb[3]:
                self.rows[-1].append((self.crumb[0], " ".join(self.crumb[1].split()), self.crumb[2]))
                self.crumb = None
            self.depth -= 1

        def handle_data(self, data):
            if self.crumb:
                self.crumb[1] += data

    parser = Crumbs()
    parser.feed(response.content.decode())
    return parser.rows
