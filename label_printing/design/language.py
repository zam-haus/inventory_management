"""
The label description language: one element per line, nesting by indentation, lengths in mm.

    # Mobile locations, 105 × 52 mm polyester
    label 105 x 52  margin 1
    row  gap 3
      qr {{ qr }}  ecc Q  max 32
      column  gap 3
        text {{ location.unique_identifier }}  font condensed  bold  invert  height 18
        image "ZAM Logo"
    text "Eigentum Betreiberverein ZAM e.V."  font condensed  center  height 4

The first line says the size: "label 105 x 52" (width × height in mm) or "label height 12", as long as
its content (Brother tape). Then elements, each on its own line: a keyword, its content (text in quotes, or
a {{ variable }} alone; text and QR codes are Django templates, texts.py) and options ("height 18", "bold",
…). Elements indented below row or column are laid out in it. # starts a comment, commas are optional.

parse() makes a Design of Elements and lists every Problem with its line; it does not stop at the first.
"""
import difflib
import re
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

FONTS = ("sans", "mono", "condensed", "ocr")
ROTATIONS = (0, 90, 180, 270)
TOKEN = re.compile(r'''"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|(\{\{.*?\}\})|([^\s,"']+)|(,)|(\S)''')
NUMBER = re.compile(r"^(\d+(?:\.\d+)?)(mm|%)?$")


@dataclass(frozen=True)
class Problem:
    line: int
    message: str


@dataclass
class Element:
    kind: str
    line: int
    content: str | None = None
    options: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def get(self, name, default=None):
        return self.options.get(name, default)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Design:
    """A label: fixed size (width and height in mm), or a height and as long as its content (width None)."""
    width: float | None = None
    height: float | None = None
    margin: tuple = (0, 0, 0, 0)  # top, right, bottom, left
    min_length: float | None = None
    max_length: float | None = None
    rotate: int = 0
    children: list = field(default_factory=list)

    def elements(self):
        for child in self.children:
            yield from child.walk()

    def images(self):
        return {element.content: element.line for element in self.elements() if element.kind == "image"}


# Option values: what each option takes.
LENGTH = "length"  # 3, 3mm
SIZE = "size"  # 3, 3mm, 50%, fill, auto
SIDE = "side"  # length or fill (QR size)
INT = "int"
SIDES = "sides"  # 1, 2 or 4 lengths like CSS: all; top and bottom, left and right; top right bottom left


def choice(*values):
    return ("choice", values)


COMMON = {"width": SIZE, "height": SIZE, "at": (LENGTH, LENGTH), "margin": SIDES}
# Rows and columns: where their elements go along them if there is room left (justify), white inside, and a
# frame around (bulge: left and right side arched outwards).
FRAME = {"justify": choice("start", "center", "end"), "padding": SIDES, "border": LENGTH, "shape": choice("rect", "round", "bulge"), "radius": LENGTH,
         "bulge": LENGTH}
ALIGN = {"left": "align", "center": "align", "right": "align", "top": "valign", "middle": "valign", "bottom": "valign"}
SPEC = {
    "row": {"options": {"gap": LENGTH, "align": choice("top", "middle", "bottom"), **FRAME, **COMMON},
            "container": True},
    "column": {"options": {"gap": LENGTH, "align": choice("left", "center", "right"), **FRAME, **COMMON},
               "container": True},
    "text": {"content": "text", "flags": {"fit": "fit", "bold": "bold", "invert": "invert", **ALIGN},
             "options": {"size": LENGTH, "lines": INT, "weight": INT, "font": choice(*FONTS), "padding": LENGTH,
                         "rotate": choice(*ROTATIONS), **COMMON}},
    "qr": {"content": "text", "flags": ALIGN,
           "options": {"ecc": choice("L", "M", "Q", "H"), "size": SIDE, "max": LENGTH, "quiet": INT, **COMMON}},
    "image": {"content": "name", "flags": {"dither": "dither", "invert": "invert", **ALIGN},
              "options": {"threshold": INT, "rotate": choice(*ROTATIONS), **COMMON}},
    "box": {"options": {"border": LENGTH, **COMMON}},
    "line": {"options": {"thickness": LENGTH, **COMMON}},
    "arrow": {"flags": {"up": "direction", "down": "direction", "left": "direction", "right": "direction"},
              "options": COMMON},
    "space": {"argument": SIZE, "options": COMMON},
}
LABEL_OPTIONS = {"margin": SIDES, "min": LENGTH, "max": LENGTH, "rotate": choice(0, 180)}


class LineError(Exception):
    pass


def tokens(text):
    """The line's tokens: ("string", value), ("variable", "{{ name }}") or ("word", value); comments and commas
    dropped."""
    found = []
    for match in TOKEN.finditer(text):
        double, single, variable, word, comma, stray = match.groups()
        if stray is not None:
            if stray == "#":
                break
            raise LineError(_("A quote is not closed.") if stray in "\"'" else _("Unexpected “%s”.") % stray)
        if double is not None or single is not None:
            found.append(("string", re.sub(r"\\(.)", r"\1", double if double is not None else single)))
        elif variable is not None:
            found.append(("variable", variable))
        elif word is not None:
            if word.startswith("#"):
                break
            found.append(("word", word))
    return found


def length(token):
    kind, value = token
    match = NUMBER.match(value) if kind == "word" else None
    if not match or match.group(2) == "%":
        raise LineError(_("“%s” is not a length in mm.") % value)
    return float(match.group(1))


def value(kind, words, name):
    """(parsed value, tokens used) for an option of this kind."""
    if not words:
        raise LineError(_("“%s” needs a value.") % name)
    token = words[0]
    if isinstance(kind, tuple) and kind[0] == "choice":
        allowed = {str(choice).lower(): choice for choice in kind[1]}
        if token[1].lower() not in allowed:
            raise LineError(_("“%(name)s” is one of %(values)s, not “%(value)s”.") % {
                "name": name, "values": ", ".join(str(choice) for choice in kind[1]), "value": token[1]})
        return allowed[token[1].lower()], 1
    if isinstance(kind, tuple):  # at x y
        if len(words) < len(kind):
            raise LineError(_("“%(name)s” needs %(count)d lengths.") % {"name": name, "count": len(kind)})
        return tuple(length(token) for token in words[:len(kind)]), len(kind)
    if kind == SIDES:
        count = 0
        while count < min(4, len(words)) and words[count][0] == "word" and re.match(r"^\d+(?:\.\d+)?(mm)?$", words[count][1]):
            count += 1
        if count in (0, 3):
            raise LineError(_("“%(name)s” takes 1, 2 or 4 lengths in mm: all sides; top and bottom, left and right; "
                              "top, right, bottom, left.") % {"name": name})
        sides = [length(token) for token in words[:count]]
        if count == 1:
            sides *= 4
        elif count == 2:
            sides *= 2
        return tuple(sides), count
    if kind == INT:
        if not token[1].isdigit():
            raise LineError(_("“%(name)s” needs a whole number, not “%(value)s”.") % {"name": name, "value": token[1]})
        return int(token[1]), 1
    if kind in (SIZE, SIDE) and token[1] in (("fill", "auto") if kind == SIZE else ("fill",)):
        return (token[1],), 1
    if kind == SIZE:
        match = NUMBER.match(token[1]) if token[0] == "word" else None
        if not match:
            raise LineError(_("“%(name)s” is a length in mm, a percentage, fill or auto, not “%(value)s”.") % {
                "name": name, "value": token[1]})
        return ("%" if match.group(2) == "%" else "mm", float(match.group(1))), 1
    return length(token), 1


def options(words, spec, kind):
    """The options of an element from its words after the content."""
    found = {}
    names = dict(spec.get("options", {}))
    flags = spec.get("flags", {})
    index = 0
    while index < len(words):
        token = words[index]
        word = token[1].lower() if token[0] == "word" else None
        if word in flags:
            found[flags[word]] = word if flags[word] != word else True
            index += 1
        elif word in names:
            found[word], used = value(names[word], words[index + 1:], word)
            index += 1 + used
        else:
            known = sorted(set(names) | set(flags))
            close = difflib.get_close_matches(token[1].lower(), known, n=1)
            hint = _(" Did you mean “%s”?") % close[0] if close else ""
            raise LineError((_("“%(word)s” is not an option of %(kind)s.") % {"word": token[1], "kind": kind}) + hint)
    if kind == "text" and found.get("bold"):
        found.setdefault("weight", 700)
    return found


def element(words, number):
    kind = words[0][1].lower()
    spec = SPEC.get(kind)
    if spec is None or words[0][0] != "word":
        close = difflib.get_close_matches(kind, list(SPEC), n=1)
        hint = _(" Did you mean “%s”?") % close[0] if close else ""
        raise LineError((_("“%s” is not an element.") % words[0][1]) + hint + " " +
                        _("Elements: %s.") % ", ".join(SPEC))
    rest = words[1:]
    item = Element(kind, number)
    if "content" in spec:
        if not rest or rest[0][0] not in ("string", "variable") and not (spec["content"] == "name" and rest[0][0] == "word"):
            raise LineError(_("%s needs its content first: text in quotes or a {{ variable }}.") % kind
                            if spec["content"] == "text" else _("image needs the name of a label image first."))
        item.content, rest = rest[0][1], rest[1:]
    if "argument" in spec and rest and rest[0][0] == "word" and (NUMBER.match(rest[0][1]) or rest[0][1] == "fill"):
        item.options["extent"], _used = value(spec["argument"], rest, kind)
        rest = rest[1:]
    item.options.update(options(rest, spec, kind))
    return item


def label(words, design):
    rest = [token[1].lower() for token in words[1:]]
    try:
        if rest[:1] == ["height"]:
            design.height = length(words[2])
            used = 3
        else:
            design.width = length(words[1])
            if len(words) < 4 or rest[1] != "x":
                raise LineError("")
            design.height = length(words[3])
            used = 4
    except (LineError, IndexError):
        raise LineError(_("Start with the size: “label 105 x 52” (width × height in mm) or “label height 12” "
                          "(as long as the content).")) from None
    if words[used:used + 1] and words[used][1].lower() == "mm":
        used += 1
    found = options(words[used:], {"options": LABEL_OPTIONS}, "label")
    design.margin = found.get("margin", (0, 0, 0, 0))
    design.min_length, design.max_length = found.get("min"), found.get("max")
    design.rotate = found.get("rotate", 0)


def parse(text):
    """(Design, [Problem])."""
    design, problems = Design(), []
    stack = []  # (indent, container element)
    previous = None  # (indent, element) of the line before
    seen_label = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.expandtabs(4)
        try:
            words = tokens(line)
        except LineError as error:
            problems.append(Problem(number, str(error)))
            continue
        if not words:
            continue
        indent = len(line) - len(line.lstrip(" "))
        try:
            if (words[0][0] == "word" and words[0][1].lower() == "label") or not seen_label:
                if seen_label:
                    raise LineError(_("The label's size is given once, in the first line."))
                seen_label = True
                if words[0][1].lower() != "label":
                    problems.append(Problem(number, _("Start with the size: “label 105 x 52” (width × height in mm) "
                                                      "or “label height 12” (as long as the content).")))
                else:
                    label(words, design)
                    continue
            item = element(words, number)
        except LineError as error:
            problems.append(Problem(number, str(error)))
            continue
        if previous and indent > previous[0] and not SPEC[previous[1].kind].get("container"):
            problems.append(Problem(number, _("Only row and column hold indented elements.")))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        (stack[-1][1].children if stack else design.children).append(item)
        if SPEC[item.kind].get("container"):
            stack.append((indent, item))
        previous = indent, item
    if not seen_label:
        problems.append(Problem(1, _("Start with the size: “label 105 x 52” (width × height in mm) or "
                                     "“label height 12” (as long as the content).")))
    return design, problems
