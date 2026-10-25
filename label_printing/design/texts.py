"""
The content of texts and QR codes in label designs: Django templates ("{{ location.name }}", filters, {% if %}),
rendered with the label's subject (layouts.designs.subject_variables). Templates are written by trusted users
only (who may change label templates), so they may use any property of the objects; nothing is escaped, a label
is not HTML.
"""
import functools
import re

from django.template import Context as TemplateContext, Engine, TemplateSyntaxError

ENGINE = Engine()
# The same with a mark where a variable has no value, to show which (only in previews).
MARK = "\x00%s\x00"
MARKING = Engine(string_if_invalid=MARK)
MARKED = re.compile("\x00([^\x00]*)\x00")


@functools.lru_cache(maxsize=1024)
def compiled(source, marking=False):
    return (MARKING if marking else ENGINE).from_string(source)


def syntax_error(source):
    """The template's syntax error as a message, or None."""
    try:
        compiled(source)
    except TemplateSyntaxError as error:
        return re.sub(r" on line \d+", "", str(error))  # the description's line is the problem's
    return None


def render(source, variables):
    return compiled(source).render(TemplateContext(variables, autoescape=False))


def missing(source, variables):
    """The variables without a value for these variables (there are none such, or None on the way), in order."""
    marked = compiled(source, marking=True).render(TemplateContext(variables, autoescape=False))
    return list(dict.fromkeys(MARKED.findall(marked)))
