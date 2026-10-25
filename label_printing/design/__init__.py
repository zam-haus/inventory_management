"""
Label designs: labels described in a small language (language.py, docs/label-designs.md) and drawn as 1-bit
images for each printer (layout.py). ZPL is only how a Zebra gets the image.
"""
from django.utils.translation import gettext as _

from . import texts
from .language import FONTS, Design, Element, Problem, parse
from .layout import Context, TooSmall, render_design

__all__ = ["FONTS", "Context", "Design", "Element", "Problem", "TooSmall", "check", "parse", "render_design"]


def check(design, images):
    """Problems beyond the language: template syntax in texts and QR codes, label images that do not exist."""
    problems = []
    for element in design.elements():
        error = texts.syntax_error(element.content) if element.kind in ("text", "qr") else None
        if error is not None:
            problems.append(Problem(element.line, error))
    for name, line in design.images().items():
        if name not in images:
            problems.append(Problem(line, _("There is no label image “%s”.") % name))
    return sorted(problems, key=lambda problem: problem.line)
