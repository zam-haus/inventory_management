"""
Label designs: labels described in a small language (language.py, docs/label-designs.md) and drawn as 1-bit
images for each printer (layout.py). ZPL is only how a Zebra gets the image.
"""
from django.utils.translation import gettext as _

from .language import FONTS, Design, Element, Problem, parse
from .layout import Context, TooSmall, render_design

__all__ = ["FONTS", "Context", "Design", "Element", "Problem", "TooSmall", "check", "parse", "render_design"]


def check(design, fields, images):
    """Problems with names: {fields} not known for the kind of label, label images that do not exist."""
    problems = []
    for name, lines in design.fields().items():
        if name not in fields:
            problems.append(Problem(lines[0], _("There is no field {%(name)s}; there are: %(fields)s.") % {
                "name": name, "fields": ", ".join("{%s}" % field for field in fields)}))
    for name, line in design.images().items():
        if name not in images:
            problems.append(Problem(line, _("There is no label image “%s”.") % name))
    return sorted(problems, key=lambda problem: problem.line)
