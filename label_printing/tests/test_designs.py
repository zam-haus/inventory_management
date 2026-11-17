"""Label designs: the description language, the layout, and label templates in printing and the admin."""
import html
import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import translation
from PIL import Image, ImageDraw

from inventory.models import LabelId, LocationLabelTemplate
from .. import services
from ..design import Context, Problem, check, parse, render_design, render_labels
from ..design.variables import Entry, Placeholder, location_contents, ownership
from ..label_urls import ItemAt
from ..image_import import import_images
from ..layouts import get_layout, layouts_for
from ..models import LabelImage
from .. import selection
from ..selection import remember_label
from .helpers import GENERATED, SETTINGS, create_printers, create_user, generated, labels
from .test_dialog import InventoryData


def black_columns(image):
    return [x for x in range(image.width) if any(image.getpixel((x, y)) == 0 for y in range(image.height))]


def black_rows(image):
    return [y for y in range(image.height) if any(image.getpixel((x, y)) == 0 for x in range(image.width))]


def blocks(columns, gap=4):
    """(first, last) of runs of black columns, split where more than gap columns are white."""
    found = []
    for column in columns:
        if found and column - found[-1][1] <= gap:
            found[-1][1] = column
        else:
            found.append([column, column])
    return [tuple(block) for block in found]


def logo(width=40, height=20):
    image = Image.new("L", (width, height), 255)
    ImageDraw.Draw(image).rectangle((0, 0, width - 1, height - 1), fill=0)
    return image


def draw(text, values=None, dpi=203, images=None, width=None, height=None, strict=False):
    design, problems = parse(text)
    assert not problems, problems
    context = Context(dpi, values or {}, images or (lambda name: None), strict=strict)
    return render_design(design, context, width, height), context.problems


@override_settings(LANGUAGE_CODE="en")
class LanguageTests(SimpleTestCase):
    def test_size_elements_and_nesting(self):
        design, problems = parse('# a comment\nlabel 105 x 52 mm  margin 1.5\nrow  gap 3, align top\n'
                                 '  qr {{ qr }}  ecc Q  max 32\n  column\n    text "Ort: {{ path }}"  size 4  bold  center\n'
                                 'text \'x\'  rotate 270  # trailing comment\n')
        self.assertEqual(problems, [])
        self.assertEqual((design.width, design.height, design.margin), (105, 52, (1.5, 1.5, 1.5, 1.5)))
        row, text = design.children
        self.assertEqual((row.kind, row.options, [child.kind for child in row.children]),
                         ("row", {"gap": 3, "align": "top"}, ["qr", "column"]))
        self.assertEqual(row.children[0].options, {"ecc": "Q", "max": 32})
        self.assertEqual(row.children[1].children[0].options, {"size": 4, "bold": True, "weight": 700, "align": "center"})
        self.assertEqual((text.content, text.options), ("x", {"rotate": 270}))
        self.assertEqual((row.children[0].content, row.children[1].children[0].content), ("{{ qr }}", "Ort: {{ path }}"))

    def test_any_length(self):
        design, problems = parse("label height 12  min 20  max 80\nspace 3")
        self.assertEqual((design.width, design.height, design.min_length, design.max_length, problems),
                         (None, 12, 20, 80, []))
        self.assertEqual(design.children[0].options, {"extent": ("mm", 3)})

    def test_problems_by_line(self):
        _design, problems = parse('label 70 x 32\ntext {{ code }}  heigth 4\nimgae "Logo"\ntext\nqr {{ qr }}  ecc X\n'
                                  'text "a"\n  text "b"\nrow  width 50%  gap x\ntext "open')
        self.assertEqual([(problem.line, problem.message) for problem in problems], [
            (2, "“heigth” is not an option of text. Did you mean “height”?"),
            (3, "“imgae” is not an element. Did you mean “image”? Elements: row, column, text, qr, barcode, list, image, "
                "box, line, arrow, space."),
            (4, "text needs its content first: text in quotes or a {{ variable }}."),
            (5, "“ecc” is one of L, M, Q, H, not “X”."),
            (7, "Only row and column hold indented elements."),
            (8, "“x” is not a length in mm."),
            (9, "A quote is not closed."),
        ])
        self.assertEqual(parse("text {{ code }}")[1][0].line, 1)  # the size first

    def test_a_list_takes_a_variable(self):
        design, problems = parse("label 50 x 50\nlist {{ contents }}  size 3  lines 2  gap 1  font condensed  bold")
        self.assertEqual((problems, design.children[0].options["weight"]), ([], 700))
        _design, problems = parse('label 50 x 50\nlist "contents"')
        self.assertEqual([problem.message for problem in problems],
                         ["list needs the variable it lists first, e.g. {{ contents }}."])

    def test_labels_turned_by_90_degrees(self):
        """Laid out across, printed on labels of height × width; tape cannot turn."""
        design, problems = parse('label 150 x 100  rotate 90\ntext "x"')
        self.assertEqual((problems, design.width, design.height, design.rotate), ([], 100, 150, 90))
        _design, problems = parse('label height 12  rotate 90\ntext "x"')
        self.assertEqual([problem.message for problem in problems], ["Only labels of a fixed size turn by 90°."])

    def test_a_barcode_takes_text(self):
        design, problems = parse("label height 18\nbarcode {{ label_id.code }}  rotate 90  quiet 5  width 16")
        self.assertEqual((problems, design.children[0].options), ([], {"rotate": 90, "quiet": 5, "width": ("mm", 16)}))
        self.assertEqual(check(parse('label 50 x 20\nbarcode "{% nope %}"')[0], set())[0].line, 2)

    def test_template_syntax_and_unknown_images(self):
        design, _problems = parse('label 50 x 20\ntext {{ code }}\ntext "{% if code %}x{% endfi %}"\nimage "Logo"')
        self.assertEqual([(problem.line, problem.message) for problem in check(design, set())], [
            (3, "Invalid block tag: 'endfi', expected 'elif', 'else' or 'endif'. Did you forget to register or "
                "load this tag?"),
            (4, "There is no label image “Logo”.")])
        self.assertEqual(parse("label 50 x 20\ntext {code}")[1][0].message,
                         "text needs its content first: text in quotes or a {{ variable }}.")  # the fields of before

    def test_placeholders_answer_any_property(self):
        self.assertEqual(Placeholder("location.name"), Placeholder("location.name"))  # always the same
        context = Context(203, {"location": Placeholder("location"), "item": Placeholder("item")})
        design, _problems = parse('label 40 x 10\ntext "{{ location.parent_location.name|upper }}"\n'
                                  'text "{{ item.sale_price|floatformat:2 }}"')
        name, price = (context.text(element) for element in design.children)
        self.assertEqual(name, Placeholder("location.parent_location.name").upper())
        self.assertRegex(name, r"^[A-Z]+ [A-Z]+$")
        self.assertRegex(price, r"^\d+\.\d\d$")
        self.assertEqual(context.problems, [])

    def test_texts_are_django_templates(self):
        variables = {"location": {"name": "Regal 1", "parent": None}, "price": Decimal("1.5")}
        texts = 'text "{{ location.name|upper }}{% if price %}: {{ price|floatformat:2 }} €{% endif %}"'
        image, problems = draw(f"label 40 x 10\n{texts}\ntext {{{{ location.parent.name }}}}", variables)
        self.assertEqual(problems[0], Problem(3, "There is no “location.parent.name”, at least not for this record."))
        context = Context(203, variables)
        design, _problems = parse(f"label 40 x 10\n{texts}\ntext '<b>&'")
        with translation.override("de"):
            self.assertEqual([context.text(element) for element in design.children], ["REGAL 1: 1,50 €", "<b>&"])
        self.assertEqual(draw("label 40 x 10\ntext {{ nope }}", strict=True)[1], [])  # printing: just empty


@override_settings(LANGUAGE_CODE="en")
class LayoutTests(SimpleTestCase):
    def test_millimetres_become_the_printers_dots(self):
        for dpi, size in ((203, (559, 256)), (300, (827, 378))):
            image, _problems = draw("label 70 x 32\nbox", dpi=dpi)
            self.assertEqual(image.size, size)
            self.assertEqual(black_columns(image)[-1], size[0] - 1)

    def test_margin_gap_and_fill(self):
        image, _problems = draw("label 40 x 10  margin 2\nrow  gap 2\n  box  width 10\n  box\n  box  width 25%", dpi=254)
        # 10 dots per mm: margin 20, box 100, gap 20, fill (130), gap 20, box 25% of 360
        self.assertEqual(blocks(black_columns(image)), [(20, 119), (140, 269), (290, 379)])
        self.assertEqual((black_rows(image)[0], black_rows(image)[-1]), (20, 79))

    def test_label_margin_per_side(self):
        image, _problems = draw("label 40 x 10  margin 1 3\nbox", dpi=254)  # top and bottom, left and right
        self.assertEqual((black_rows(image)[0], black_rows(image)[-1]), (10, 89))
        self.assertEqual((black_columns(image)[0], black_columns(image)[-1]), (30, 369))
        image, _problems = draw("label 40 x 10  margin 1 2 3 4\nbox", dpi=254)  # top, right, bottom, left
        self.assertEqual((black_rows(image)[0], black_rows(image)[-1]), (10, 69))
        self.assertEqual((black_columns(image)[0], black_columns(image)[-1]), (40, 379))

    def test_text_then_image_with_a_fixed_gap(self):
        """The image follows the text, however long it is; on a label of fixed length the text shrinks for it."""
        text = 'label height 12  margin 1\nrow  gap 2\n  text {{ name }}  size 5\n  image "Logo"  height 6'
        ends = []
        for name in ("Bohrer", "Akkuschrauber 18 V"):
            image, problems = draw(text, {"name": name}, dpi=254, images=lambda name: logo())
            text_block, logo_block = blocks(black_columns(image), gap=15)[-2:]
            # 2 mm, plus the little room a glyph keeps beside it
            self.assertIn(logo_block[0] - text_block[1] - 1, range(20, 24), name)
            self.assertEqual((logo_block[1] - logo_block[0] + 1, problems), (120, []))  # 6 mm high, twice as wide
            ends.append(image.width)
        self.assertLess(ends[0], ends[1])
        long = "Akku-Bohrschrauber mit Schnellspannfutter"
        image, problems = draw('label 70 x 12  margin 1\nrow  gap 2\n  text {{ name }}  width auto\n  image "Logo"  height 6',
                               {"name": long}, dpi=254, images=lambda name: logo())
        text_block, logo_block = blocks(black_columns(image), gap=15)[-2:]
        self.assertIn(logo_block[0] - text_block[1] - 1, range(20, 24))  # the text shrank to leave room
        self.assertEqual((logo_block[1] - logo_block[0] + 1, problems), (120, []))
        self.assertLessEqual(logo_block[1], 689)

    def test_longest_text_decides_where_the_image_starts(self):
        text = ('label height 12  margin 1\nrow  gap 2\n  column\n    text {{ name }}  size 5\n    text {{ path }}  size 2.5\n'
                '  image "Logo"')
        for name, path in (("Bohrer", "Werkstatt › Regal 303 › Fach a"), ("Akkuschrauber 18 V", "Lager")):
            image, _problems = draw(text, {"name": name, "path": path}, dpi=254, images=lambda name: logo())
            *texts, logo_block = blocks(black_columns(image), gap=15)
            self.assertIn(logo_block[0] - max(block[1] for block in texts) - 1, range(20, 24), name)

    def test_margins_around_elements(self):
        """An element's box is its content and its margin: images, QR codes and texts keep their room."""
        image, _problems = draw('label height 10\nrow\n  image "L"  height 4  margin 1\n  image "L"  height 4  margin 0 2 0 3',
                                dpi=254, images=lambda name: logo())
        self.assertEqual((image.width, blocks(black_columns(image))), (230, [(10, 89), (130, 209)]))
        image, _problems = draw('label height 10\nrow\n  qr "HTTPS://I.ZAM.HAUS/K7R4XD"  quiet 0  margin 1\n'
                                '  text "I"  size 4  margin 0 5', dpi=254)
        qr_block, text_block = blocks(black_columns(image))
        self.assertEqual(qr_block[0], 10)
        self.assertGreaterEqual(text_block[0] - qr_block[1], 10 + 50)  # the QR code's margin and the text's
        self.assertEqual(parse('label 10 x 10\ntext "a"  margin 1 2 3')[1][0].message,
                         "“margin” takes 1, 2 or 4 lengths in mm: all sides; top and bottom, left and right; top, "
                         "right, bottom, left.")

    def test_frames_justify_and_padding(self):
        image, _problems = draw("label 40 x 10\nrow  border 0.5  shape bulge  bulge 2\n  space", dpi=254)
        self.assertEqual((image.getpixel((0, 50)), image.getpixel((2, 2)), image.getpixel((200, 2))), (0, 1, 0))
        self.assertEqual(image.getpixel((200, 50)), 1)  # only a frame
        image, _problems = draw("label 40 x 10\nrow  border 0.5  shape round  radius 3\n  space", dpi=254)
        self.assertEqual((image.getpixel((0, 50)), image.getpixel((1, 1))), (0, 1))
        # a bulged frame keeps its content clear of the arches
        image, _problems = draw("label 40 x 10\nrow  border 0.5  shape bulge  bulge 2  padding 0 1\n  box  width 5", dpi=254)
        self.assertEqual(blocks(black_columns(image.crop((0, 40, 400, 60))))[1][0], 5 + 20 + 10)
        image, _problems = draw("label 40 x 10\nrow  justify center\n  box  width 10", dpi=254)
        self.assertEqual(blocks(black_columns(image)), [(150, 249)])
        image, _problems = draw("label 40 x 10\nrow  justify end  padding 0 2\n  box  width 10", dpi=254)
        self.assertEqual(blocks(black_columns(image)), [(280, 379)])

    def test_auto_across_is_as_large_as_the_content(self):
        """A price frame or inverted text below a long name: as wide as itself with width auto, else as the column."""
        design = ('label 40 x 10\ncolumn  align left\n  text "A long name for an item"  height 50%%\n'
                  '  %s\n    text "1"')
        framed, _problems = draw(design % "row  border 0.5  shape bulge", dpi=254)
        hugging, _problems = draw(design % "row  border 0.5  shape bulge  width auto", dpi=254)
        self.assertGreater(blocks(black_columns(framed.crop((0, 50, 400, 100))))[-1][1], 390)  # the whole width
        self.assertLess(blocks(black_columns(hugging.crop((0, 50, 400, 100))))[-1][1], 150)
        inverted, _problems = draw('label 40 x 10\ncolumn  align left\n  text "A long name for an item"  height 50%\n'
                                   '  text "1"  invert  width auto', dpi=254)
        self.assertLess(blocks(black_columns(inverted.crop((0, 50, 400, 100))))[-1][1], 100)

    def test_words_are_split_only_if_nothing_else_fits(self):
        from .. import render
        loaded, lines = render.fit("Senkkopfschrauben M4", 300, 120, max_lines=3)
        self.assertEqual(lines, ["Senkkopfschrauben", "M4"])  # smaller, not "Senkkopfschraube" / "n M4"
        loaded, lines = render.fit("Senkkopfschrauben", 20, 120, max_lines=3)  # too narrow even at the smallest
        self.assertGreater(len(lines), 1)

    def test_underscores_are_a_line_to_write_on(self):
        image, _problems = draw('label 40 x 10\ntext "{{ name|default:\'__________\' }}"', {"name": None}, dpi=254)
        self.assertEqual(len(blocks(black_columns(image), gap=1)), 1)  # unbroken, whatever the font

    def test_a_text_of_nothing_takes_no_room(self):
        """E.g. the code of an item stored nowhere: no inverted box either."""
        design = 'label 40 x 10\nrow  gap 0\n  box  width 5\n  text "{{ code }}"  font mono  bold  invert\n  box  width 5'
        empty, _problems = draw(design, {"code": ""}, dpi=254)
        self.assertEqual(blocks(black_columns(empty), gap=1), [(0, 99)])  # the boxes meet
        coded, _problems = draw(design, {"code": "R1"}, dpi=254)
        self.assertGreater(len(black_columns(coded)), 100)

    def test_a_row_or_column_showing_nothing_is_left_out(self):
        design = ('label 40 x 10\nrow  gap 2\n  row  border 0.5  shape bulge  width auto\n'
                  '    text "{% if price %}€ {{ price }}{% endif %}"\n  box  width 5')
        priced, _problems = draw(design, {"price": "1,50"}, dpi=254)
        unpriced, _problems = draw(design, {"price": None}, dpi=254)
        self.assertEqual(len(blocks(black_columns(priced))), 2)
        self.assertEqual(blocks(black_columns(unpriced)), [(0, 49)])  # no frame, no gap: the box comes first
        # Blanks keep their room: an empty frame, about as wide as a price.
        empty, _problems = draw(design.replace("{% endif %}", "{% else %}{{ ''|ljust:6 }}{% endif %}"),
                                {"price": None}, dpi=254)
        frame, box = blocks(black_columns(empty))
        self.assertGreater(frame[1] - frame[0], 50)
        self.assertEqual(empty.getpixel(((frame[0] + frame[1]) // 2, 50)), 1)  # nothing inside
        # A frame around just spaces stays, so does one with anything but texts.
        image, _problems = draw('label 40 x 10\nrow  border 0.5\n  text ""\n  box  width 5', dpi=254)
        self.assertEqual(image.getpixel((0, 50)), 0)

    def test_text_in_a_row_is_as_wide_as_it_needs(self):
        image, _problems = draw('label 40 x 10\nrow  border 0.5  justify center\n  text "MM"\n  text "x"  height 40%  bottom',
                                dpi=254)
        inner = blocks(black_columns(image.crop((10, 10, 390, 90))), gap=8)
        self.assertGreater(inner[0][0], 50)  # centred, not spread over the row

    def test_any_length_within_min_and_max(self):
        def width(text, name):
            return draw(text, {"name": name}, dpi=254)[0].width
        self.assertEqual(width("label height 10  margin 1\ntext {{ name }}  size 4", ""), 20)
        self.assertEqual(width("label height 10  margin 1  min 30\ntext {{ name }}  size 4", "a"), 300)
        self.assertEqual(width("label height 10  margin 1  max 40\ntext {{ name }}  size 4", "a" * 80), 400)

    def test_qr_codes_have_whole_dots_per_module(self):
        image, problems = draw('label 30 x 30\nqr "HTTPS://I.ZAM.HAUS/K7R4XD"  quiet 0', dpi=203)
        rows = black_rows(image)
        self.assertEqual(((rows[-1] - rows[0] + 1) % 21, problems), (0, []))  # version 1: 21 modules
        image, problems = draw('label 30 x 30\nqr "HTTPS://I.ZAM.HAUS/K7R4XD"  max 10  quiet 0', dpi=203)
        self.assertLessEqual(black_rows(image)[-1] - black_rows(image)[0] + 1, 80)
        _image, problems = draw('label 30 x 4\nqr "HTTPS://I.ZAM.HAUS/K7R4XD"')
        self.assertEqual(problems[0].message, "The QR code does not fit: it needs 6.3 mm at least.")
        with self.assertRaises(Exception):
            draw('label 30 x 4\nqr "HTTPS://I.ZAM.HAUS/K7R4XD"', strict=True)

    def test_text_options(self):
        image, _problems = draw('label 40 x 10\ntext "MMMM"  invert', dpi=254)
        self.assertEqual(image.getpixel((0, 0)), 0)  # white on black
        image, _problems = draw('label 40 x 10\ntext "I"  size 6  right', dpi=254)
        self.assertGreater(black_columns(image)[0], 300)
        image, _problems = draw('label 10 x 40\ntext "Lange Zeile"  rotate 270', dpi=254)
        rows = black_rows(image)
        self.assertGreater(rows[-1] - rows[0], 200)  # runs along the height
        image, _problems = draw('label 30 x 20\ntext "eins zwei drei vier fünf"  size 4  lines 2', dpi=254)
        self.assertGreater(black_rows(image)[-1] - black_rows(image)[0], 50)  # two lines

    def test_images_scaled_and_black_and_white(self):
        grey = Image.new("L", (100, 50), 100)
        image, _problems = draw('label 40 x 20\nimage "Logo"', dpi=254, images=lambda name: grey)
        self.assertEqual(blocks(black_columns(image)), [(0, 399)])  # 2:1 fills 40 × 20 mm
        image, _problems = draw('label 40 x 20\nimage "Logo"  threshold 50', dpi=254, images=lambda name: grey)
        self.assertEqual(black_columns(image), [])
        image, _problems = draw('label 40 x 20\nimage "Logo"  dither', dpi=254, images=lambda name: grey)
        self.assertGreater(len(black_columns(image)), 300)
        self.assertLess(sum(image.getpixel((x, 100)) == 0 for x in range(400)), 400)
        _image, problems = draw('label 40 x 20\nimage "Logo"', images=lambda name: None)
        self.assertEqual(problems[0].message, "There is no label image “Logo”.")

    def test_shapes_and_absolute_places(self):
        image, _problems = draw("label 20 x 10\ncolumn\n  line  thickness 1\nbox  at 15 5  width 2  height 2", dpi=254)
        self.assertEqual(image.getpixel((150, 50)), 0)
        self.assertEqual(image.getpixel((100, 50)), 1)
        image, _problems = draw("label 20 x 10\narrow up", dpi=254)
        self.assertEqual((image.getpixel((100, 5)), image.getpixel((5, 95)), image.getpixel((5, 5))), (0, 0, 1))
        _image, problems = draw("label 20 x 10\nrow\n  box  width 15\n  box  width 15", dpi=254)
        self.assertEqual(problems[0].message, "The elements are 10.0 mm too long for this row.")

    def test_a_list_goes_on_on_further_labels(self):
        """As many entries as fit on each label, the rest on the next, the whole design each time; page and pages
        number them."""
        design, _problems = parse('label 40 x 20  margin 1\ntext "{{ page }}/{{ pages }}"  size 4\n'
                                  'list {{ contents }}  size 3  gap 1')
        contents = [Entry(f"{number} Stk", f"Teil {number}") for number in range(1, 9)]
        pages = render_labels(design, Context(254, {"contents": contents}))
        lines = [len(blocks(black_rows(image), gap=2)) - 1 for image in pages]  # text rows less the page number
        self.assertEqual((len(pages), sum(lines)), (3, 8))
        self.assertEqual(lines[:2], [lines[0]] * 2)  # full labels, the rest on the last
        self.assertEqual({image.size for image in pages}, {(400, 200)})
        self.assertEqual(len(render_labels(design, Context(254, {"contents": contents[:2]}))), 1)

    def test_a_list_shows_amounts_names_label_ids_and_notes(self):
        image, problems = draw("label 60 x 20\nlist {{ contents }}  size 3", {"contents": [
            Entry("12 Stk", "Schrauben"), Entry("", "Akkuschrauber", "K7R-4XD"),
            Entry("", "Akkuschrauber", "K7R-4XD", "Fremdeigentum: Erika")]}, dpi=254)
        self.assertEqual(problems, [])
        first, second, third, note = blocks(black_rows(image), gap=2)
        row = lambda block: black_columns(image.crop((0, block[0], 600, block[1] + 1)))
        self.assertGreater(min(row(second)), min(row(first)))  # names after the amounts' column
        self.assertEqual(row(third), row(second))  # the same name and label ID
        self.assertAlmostEqual(min(row(note)), min(row(second)), delta=4)  # on a line of its own, below the name
        _image, problems = draw("label 60 x 10\nlist {{ nothing }}", {})
        self.assertEqual([problem.message for problem in problems], ["“nothing” is not a list."])

    def test_a_list_without_room_for_one_entry_is_a_problem(self):
        design, _problems = parse("label 40 x 5\nlist {{ contents }}  size 8")
        context = Context(254, {"contents": [Entry("1", "Teil")]})
        self.assertEqual(len(render_labels(design, context)), 1)
        self.assertEqual([problem.message for problem in context.problems], ["There is no room left for this list."])

    def test_code_128(self):
        """Set B for text, set C for an even number of digits; the same modules as reportlab draws."""
        from ..render import code128
        self.assertEqual(code128("F3PND2"), "11010010000100011000101100101110011101110110101110001101011000100011001110"
                                            "010110000100101100011101011")
        self.assertEqual((len(code128("123456")), code128("1234")[:11]), (68, "11010011100"))  # start C
        self.assertEqual((code128("Ä"), code128("")), (None, None))

    def test_a_barcode_across_a_tape(self):
        """rotate 90: across the tape, the bars along it, whole dots per module, centred with its quiet zone."""
        image, problems = draw("label 20 x 16.5\nbarcode {{ code }}  rotate 90  quiet 5", {"code": "F3PND2"}, dpi=360)
        self.assertEqual(problems, [])
        column = [image.getpixel((100, y)) for y in range(image.height)]
        dark = [y for y, value in enumerate(column) if value == 0]
        self.assertEqual(dark[-1] - dark[0] + 1, 101 * 2)  # 101 modules of 2 dots, from the first bar to the last
        self.assertEqual(dark[0], (image.height - 111 * 2) // 2 + 5 * 2)
        self.assertTrue(all(image.getpixel((x, dark[0])) == 0 for x in range(image.width)))  # a bar along the tape
        rows = [[image.getpixel((x, y)) for x in range(0, image.width, 37)] for y in range(image.height)]
        self.assertEqual(rows, [[row[0]] * len(row) for row in rows])

    def test_a_barcode_too_small_is_a_problem(self):
        _image, problems = draw("label 20 x 9\nbarcode {{ code }}  rotate 90", {"code": "F3PND2"}, dpi=360)
        self.assertEqual([problem.message for problem in problems],
                         ["The barcode does not fit: it needs 17.1 mm at least."])
        _image, problems = draw("label 40 x 9\nbarcode {{ code }}", {"code": "Ä"})
        self.assertEqual([problem.message for problem in problems],
                         ["A Code 128 barcode takes letters, digits and signs, not “Ä”."])

    def test_a_label_printed_inverted(self):
        """invert: the whole label white (its colour) on black, e.g. pallet rack slots."""
        image, problems = draw("label 20 x 10  invert\nrow\n  box  width 5\n  space", dpi=254)
        self.assertEqual(problems, [])
        self.assertEqual((image.getpixel((10, 50)), image.getpixel((150, 50))), (255, 0))  # the box white, the rest black
        self.assertTrue(parse("label 20 x 10  invert")[0].invert)

    def test_a_label_turned_by_90_degrees(self):
        """The design across (here a box at its left), turned clockwise: the box at the top of the label."""
        image, problems = draw("label 40 x 20  rotate 90\nrow\n  box  width 10\n  space", dpi=254)
        self.assertEqual((image.size, problems), ((200, 400), []))
        self.assertEqual((black_rows(image)[0], black_rows(image)[-1]), (0, 99))
        self.assertEqual((black_columns(image)[0], black_columns(image)[-1]), (0, 199))

    def test_text_crowded_out_is_a_problem_not_an_error(self):
        _image, problems = draw("label height 9  margin 1\ncolumn\n  text {{ code }}  invert\n  text {{ path }}  size 7",
                                {"code": "A1", "path": "Raum / Regal"})
        self.assertEqual([(problem.line, problem.message) for problem in problems],
                         [(3, "There is no room left for this text.")])
        # also when only a sliver is left for it (here 2 dots for the third text): too small to see
        _image, problems = draw("label 16.5 x 16.5\nrow  gap 1.5  padding 0 1\n  text {{ code }}  rotate 270  font mono\n"
                                '  text "ZAMid"  rotate 270  font sans  weight 800\n  text {{ code }}  rotate 270  font mono',
                                {"code": "F3P-ND2"}, dpi=360)
        self.assertEqual([(problem.line, problem.message) for problem in problems],
                         [(5, "There is no room left for this text.")])


@override_settings(**SETTINGS)
class TemplateTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        self.enterContext(override_settings(MEDIA_ROOT=media))

    def template(self, description, subject_type="location", name="T"):
        return LocationLabelTemplate.objects.create(name=name, subject_type=subject_type, description=description)

    def test_size_from_the_description_and_where_offered(self):
        fixed = self.template("label 57 x 32\ntext {{ location.unique_identifier }}")
        tape = self.template("label height 12\ntext {{ location.unique_identifier }}")
        wide = self.template("label height 24\ntext {{ location.unique_identifier }}")
        self.assertEqual((fixed.label_width, fixed.label_height, tape.label_width, tape.size_text),
                         (57, 32, None, "12 mm tape"))
        keys = lambda printer, medium: [layout.key for layout in layouts_for("location", printer, medium)]
        self.assertIn(f"design:{fixed.pk}", keys(self.zebra, self.labels))
        self.assertNotIn(f"design:{tape.pk}", keys(self.zebra, self.labels))
        self.assertIn(f"design:{tape.pk}", keys(self.brother, self.tape))
        self.assertNotIn(f"design:{wide.pk}", keys(self.brother, self.tape))
        self.assertNotIn(f"design:{fixed.pk}", keys(self.brother, self.tape))

    def test_templates_with_images_are_offered(self):
        # An image does not make a template undrawable, also before it is uploaded (the template lists that problem
        # itself); a QR code too small still does.
        keys = lambda: [layout.key for layout in layouts_for("location", self.zebra, self.labels)]
        logo = self.template('label 57 x 32\nrow\n  qr {{ qr }}\n  image "ZAM Logo"')
        tiny = self.template('label 57 x 32\nrow\n  qr {{ qr }}  max 3\n  image "ZAM Logo"', name="Tiny")
        self.assertIn(f"design:{logo.pk}", keys())
        self.assertNotIn(f"design:{tiny.pk}", keys())

    def test_printed_on_matching_labels_only(self):
        from ..layouts.designs import fits
        fixed = self.template("label 57 x 32\ntext {{ location.unique_identifier }}")
        endless = self.template("label height 12\ntext {{ location.unique_identifier }}")
        long_tape = self.template("label 40 x 12\ntext {{ location.unique_identifier }}")
        narrow = self.template("label height 3.5\ntext {{ location.unique_identifier }}")
        unknown = labels(self.zebra, save=False, name="?")
        self.assertFalse(fits(fixed, unknown))  # labels of unknown size match no template
        self.assertTrue(fits(fixed, labels(self.zebra, save=False, name="a", width_mm=58, height_mm=32)))
        self.assertFalse(fits(fixed, labels(self.zebra, save=False, name="b", width_mm=57, height_mm=25)))
        cut = labels(self.brother, save=False, name="12 mm, 40 mm long", ptouch_tape=12, height_mm=40)
        self.assertEqual((fits(endless, self.tape), fits(long_tape, self.tape)), (True, True))  # endless tape
        self.assertEqual((fits(endless, cut), fits(long_tape, cut)), (False, True))
        self.assertTrue(fits(narrow, labels(self.brother, save=False, name="3.5 mm", ptouch_tape=4)))
        with self.assertRaisesMessage(services.PrintError, "This layout does not fit"):
            services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{endless.pk}",
                            subject_type="location", subjects=[self.part])

    def test_slightly_larger_zebra_labels_take_a_template(self):
        """Up to 2.5 mm larger, drawn to their size: 100 × 150 mm on 101.6 × 152.4 mm; not smaller, not much larger."""
        from ..layouts.designs import size_fits
        template = self.template("label 100 x 150\ntext {{ location.unique_identifier }}")
        for (width, height), fits in (((100, 150), True), ((101.6, 152.4), True), ((99, 150), True),
                                      ((98, 150), False), ((103, 150), False), ((101.6, 155), False)):
            with self.subTest(width=width, height=height):
                medium = labels(self.zebra, save=False, name="?", width_mm=width, height_mm=height)
                self.assertEqual(size_fits(template, medium), fits)

    def test_printed_on_tape_as_long_as_the_content(self):
        template = self.template('label height 12  margin 0.5\nrow  gap 1\n  qr {{ qr }}\n  text {{ location.descriptive_identifier }}')
        rendered, = services.render(get_layout(f"design:{template.pk}"), [self.part], self.tape, preview=True)
        self.assertEqual(rendered.image.height, 70)  # E550W, 12 mm tape
        self.assertEqual(rendered.snapshot["code"], "R303.a")
        job = services.submit(printer=self.brother, medium=self.tape, layout_key=f"design:{template.pk}",
                              subject_type="location", subjects=[self.part], copies=1)
        self.assertEqual(job.label_code, "R303.a")

    def test_item_and_label_id_templates(self):
        item = self.template('label 57 x 32\nrow\n  qr {{ qr }}\n  column\n    text {{ item.name }}\n'
                             '    text "{{ item.sale_price|floatformat:2 }} € / {{ item.measurement_unit.short }}"', "item")
        rendered, = services.render(get_layout(f"design:{item.pk}"), [ItemAt(self.item, self.part)],
                                    self.labels, preview=True)
        self.assertEqual(rendered.image.size, (456, 256))
        self.assertFalse(LabelId.objects.exists())  # previews hand out no IDs
        lid = LabelId.objects.create(code="K7R4XD")
        labelid = self.template('label 57 x 32\nrow\n  qr {{ qr }}\n  column\n'
                                '    text {{ label_id.code|slice:":3" }}\n    text {{ label_id.code|slice:"3:" }}', "labelid")
        rendered, = services.render(get_layout(f"design:{labelid.pk}"), [lid], self.labels, preview=True)
        self.assertEqual(rendered.label_code, "K7R4XD")

    def test_items_on_removable_labels_at_most_20_mm_high(self):
        """One template for items and their prices ("Artikel"; the price tags are not offered any more): on 50 × 18 mm
        removable paper, and on the 47 × 24 mm removable polyester while it lasts."""
        from inventory.models import LocationLabelTemplate as Template
        for width, height in ((50, 18), (47, 24)):
            medium = labels(self.zebra, name=f"{width} × {height}", width_mm=width, height_mm=height)
            offered = [layout.key for layout in layouts_for("item", medium.printer, medium)]
            template = Template.objects.get(name="Artikel", label_width=width, label_height=height)
            self.assertEqual(offered, [f"design:{template.pk}"])
            rendered, = services.render(get_layout(f"design:{template.pk}"), [ItemAt(self.item, self.part)], medium,
                                        preview=True)
            self.assertEqual(rendered.snapshot["price"], "0.15 € / Stk")
        self.assertFalse(Template.objects.filter(name="Preisschild", is_active=True).exists())

    def test_templates_for_every_label(self):
        """The migrations' templates: each kind for the Zebra labels in use and every Brother tape width."""
        from ..layouts.designs import problems_of
        from ..models import Printer
        p900 = Printer.objects.create(name="P900W", slug="p900", language="ptouch", model="P900W", dpi=360,
                                      host="127.0.0.1")
        media = {f"tape{width}": labels(p900, name=f"{width} mm", ptouch_tape=width)
                 for width in (9, 12, 18, 24, 36)}
        media |= {f"{width}x{height}": labels(self.zebra, name=f"{width}x{height}",
                                                                  width_mm=width, height_mm=height)
                  for width, height in ((57, 32), (60, 30), (70, 32), (105, 52))}
        for kind in GENERATED:
            for size, medium in media.items():
                with self.subTest(kind=kind, size=size):
                    template = generated(kind, size)
                    self.assertEqual(problems_of(template)[1], [])
                    offered = [layout.key for layout in layouts_for(template.subject_type, medium.printer, medium)]
                    # deactivated on the development server, e.g. items on 9 mm tape: not offered
                    self.assertEqual(f"design:{template.pk}" in offered, template.is_active)

    def test_contents_of_a_location(self):
        """What is right at it: the locations in it with their code, then by name (numbers by value) items with their
        amount, quick items without one, unique items with their label ID and, where the owners differ, whose they are
        if not the ZAM's (the public first name only); deleted items and what is further below are not."""
        from inventory.models import Item, ItemLocation, Location, UniqueItem
        for name, amount in (("Schraube 10", 5), ("Schraube 9", -3), ("Notiz", None)):
            ItemLocation.objects.create(item=Item.objects.create(name=name, measurement_unit=self.unit),
                                        location=self.shelf, amount=amount)
        gone = Item.objects.create(name="Weg", measurement_unit=self.unit)
        ItemLocation.objects.create(item=gone, location=self.shelf, amount=1)
        gone.delete()
        drill = Item.objects.create(name="Bohrer", measurement_unit=self.unit, kind=Item.Kind.SERIALIZED)
        UniqueItem.objects.create(item=drill, name="rot", location=self.shelf)
        UniqueItem.objects.create(item=drill, name="blau", location=self.shelf, owner_first_name="Erika")
        UniqueItem.objects.create(item=drill, name="grün", location=self.shelf, owner_contact="Nur intern")
        parts = [Location.objects.get(pk=pk) for pk in (self.part.pk, self.other_part.pk)]
        self.assertEqual([str(entry) for entry in location_contents(self.shelf)],
                         [f"Fach a {parts[0].unique_identifier}", f"Fach b {parts[1].unique_identifier}",
                          "• Bohrer blau not the ZAM's: Erika", "• Bohrer grün not the ZAM's", "• Bohrer rot", "Notiz",
                          "~3 Stk Schraube 9", "5 Stk Schraube 10"])
        self.assertEqual(location_contents(parts[0]), [Entry("100 Stk", "Schrauben M4")])
        # (owned, owner, differ): different owners here, the ZAM's items there; the label says it once
        self.assertEqual((ownership(self.shelf), ownership(parts[0])), ((True, "", True), (True, "", False)))

    def test_whose_the_contents_are_said_once_if_it_is_one_owner(self):
        from inventory.models import Item, Location, LocationType, UniqueItem
        box = Location.objects.create(name="Kiste 9", short_name="K9", type=LocationType.objects.create(name="Kiste"),
                                      parent_location=self.shelf)
        drill = Item.objects.create(name="Bohrer", measurement_unit=self.unit, kind=Item.Kind.SERIALIZED)
        self.assertEqual(ownership(box), (False, "", False))  # nothing there: nothing to say
        UniqueItem.objects.create(item=drill, name="blau", location=box, owner_first_name="Erika")
        UniqueItem.objects.create(item=drill, name="rot", location=box, owner_first_name="Erika")
        self.assertEqual(ownership(box), (True, "Erika", False))
        self.assertEqual([str(entry) for entry in location_contents(box)], ["• Bohrer blau", "• Bohrer rot"])

    def test_who_is_responsible(self):
        from django.contrib.auth.models import Group
        from accounts.models import Team
        self.shelf.responsible_teams.add(Team.objects.create(group=Group.objects.create(name="Holzwerkstatt")),
                                         Team.objects.create(group=Group.objects.create(name="Hausmeister")))
        variables = selection.variables_for("location", self.shelf)
        self.assertEqual(str(variables["responsible"]), "Hausmeister, Holzwerkstatt")

    def test_a_contents_label_goes_on_on_further_labels_of_one_job(self):
        from inventory.models import Item, ItemLocation
        for number in range(30):
            ItemLocation.objects.create(item=Item.objects.create(name=f"Teil {number}", measurement_unit=self.unit),
                                        location=self.shelf, amount=number + 1)
        template = self.template('label 57 x 32  margin 1\ntext "{{ location.unique_identifier }} {{ page }}/{{ pages }}"'
                                 '  size 4\nlist {{ contents }}  size 3', name="Inhalt")
        layout = get_layout(f"design:{template.pk}")
        rendered, = services.render(layout, [self.shelf], self.labels, preview=True)
        self.assertGreater(len(rendered.images), 1)
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=layout.key, subject_type="location",
                              subjects=[self.shelf], copies=2)
        self.assertEqual((job.pages, len(job.snapshot)), (len(rendered.images) * 2, 1))
        self.assertEqual(job.payload.count(b"^XA"), len(rendered.images))

    def test_codes_are_printed_dot_exact(self):
        """In the images sent to the printer (services.render: Zebra as drawn, Brother in high quality squeezed across
        the tape) every QR module is a block of whole dots, all alike, and the barcode's bars are whole dots per
        module, exactly the modules of its Code 128."""
        from ..render import code128, qr

        def check_qr(image, content):
            matrix = qr(content).matrix
            pixels = image.load()
            x0 = next(x for x in range(image.width) if any(pixels[x, y] == 0 for y in range(image.height)))
            y0 = next(y for y in range(image.height) if pixels[x0, y] == 0)
            width = next(x for x in range(x0, image.width) if pixels[x, y0] != 0) - x0  # the finder: 7 modules
            height = next(y for y in range(y0, image.height) if pixels[x0, y] != 0) - y0
            self.assertEqual((width % 7, height % 7), (0, 0))
            kx, ky = width // 7, height // 7
            for row, line in enumerate(matrix):
                for column, dark in enumerate(line):
                    block = {pixels[x0 + column * kx + dx, y0 + row * ky + dy] == 0
                             for dx in range(kx) for dy in range(ky)}
                    self.assertEqual(block, {bool(dark & 1)}, (row, column))

        def modules(values):
            """The runs of one line of dots, as modules of the narrowest run's width."""
            runs, start = [], 0
            for index in range(1, len(values) + 1):
                if index == len(values) or values[index] != values[start]:
                    runs.append((values[start], index - start))
                    start = index
            runs = runs[1:-1]  # the white around the bars
            narrowest = min(length for _value, length in runs)
            self.assertTrue(all(length % narrowest == 0 for _value, length in runs))
            return "".join(("1" if value == 0 else "0") * (length // narrowest) for value, length in runs)

        def dark(image, points):
            return [0 if image.getpixel(point) == 0 else 255 for point in points]

        location = selection.variables_for("location", self.part)["qr"]
        flat = self.template('label 57 x 32  margin 1\ncolumn  gap 1\n  qr {{ qr }}  quiet 1  max 18\n'
                             '  barcode "1234"  quiet 2  height 8', name="Zebra")
        rendered, = services.render(get_layout(f"design:{flat.pk}"), [self.part], self.labels, preview=True)
        last = black_rows(rendered.image)[-1]  # the barcode's bottom, 8 mm below its top
        check_qr(rendered.image.crop((0, 0, rendered.image.width, last - 70)), location)  # the QR code above it
        bars = dark(rendered.image, [(x, last - 5) for x in range(rendered.image.width)])
        self.assertEqual(modules(bars), code128("1234"))
        tape = self.template('label height 12  margin 0 1\nrow  gap 1\n  qr {{ qr }}  quiet 1\n'
                             '  barcode "1234"  rotate 90  quiet 2  width 6', name="Band")
        rendered, = services.render(get_layout(f"design:{tape.pk}"), [self.part], self.tape, preview=True,
                                    quality="high")
        check_qr(rendered.image, location)
        column = rendered.image.width - 20  # within the barcode, its bars along the tape
        bars = dark(rendered.image, [(column, y) for y in range(rendered.image.height)])
        self.assertEqual(modules([255] + bars + [255]), code128("1234"))

    def test_mistakes_and_too_small_labels_are_refused(self):
        broken = self.template('label 57 x 32\ntext "{% nope %}"')
        with self.assertRaisesMessage(services.PrintError, "Line 2: Invalid block tag: 'nope'"):
            services.render(get_layout(f"design:{broken.pk}"), [self.part], self.labels, preview=True)
        tiny = self.template("label 57 x 32\nqr {{ qr }}  max 3")
        with self.assertRaisesMessage(services.PrintError, "The content does not fit"):
            services.render(get_layout(f"design:{tiny.pk}"), [self.part], self.labels, preview=True)

    def test_label_images_in_designs(self):
        image = LabelImage(name="ZAM Logo", crop_left=10)
        out = io.BytesIO()
        logo(80, 20).save(out, format="PNG")
        image.image.save("logo.png", ContentFile(out.getvalue()), save=False)
        image.full_clean()
        image.save()
        self.assertEqual(image.cropped().size, (70, 20))
        template = self.template('label 57 x 32\nimage "ZAM Logo"')
        rendered, = services.render(get_layout(f"design:{template.pk}"), [self.part], self.labels, preview=True)
        (first, last), = blocks(black_columns(rendered.image))  # 7:2 across 57 mm
        self.assertEqual(first, 0)
        self.assertGreaterEqual(last, 454)

    def test_import_of_images_and_archives(self):
        out = io.BytesIO()
        logo().save(out, format="PNG")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as files:
            files.writestr("iso7010/W001.png", out.getvalue())
            files.writestr("iso7010/readme.txt", "no image")
            files.writestr("__MACOSX/iso7010/._W001.png", "junk")
        LabelImage.objects.create(name="W001", image=SimpleUploadedFile("w.png", out.getvalue()))
        created, skipped = import_images([SimpleUploadedFile("signs.zip", archive.getvalue()),
                                          SimpleUploadedFile("broken.png", b"no image")])
        self.assertEqual(([image.name for image in created], [name for name, _why in skipped]), (["W001 2"], ["broken.png"]))


@override_settings(**SETTINGS)
class AdminTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.admin = get_user_model().objects.create_superuser("admin", password="pw")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_list_shows_a_sample_of_each_template(self):
        zamid = LocationLabelTemplate.objects.get(name="ZAMid", label_width=None, label_height=12)
        response = self.client.get(reverse("admin:inventory_locationlabeltemplate_changelist"), {"q": "ZAMid"})
        sample = reverse("label_template_sample", args=[zamid.pk])
        self.assertContains(response, f'<img src="{sample}?v=')
        image = Image.open(io.BytesIO(self.client.get(sample).content))
        self.assertEqual(image.height, 150)  # 12 mm tape on the nominal tape printer (P900W, 360 dpi)
        self.client.force_login(create_user("reader"))
        self.assertEqual(self.client.get(sample).status_code, 403)

    def samples(self, query, user=None):
        """The samples of the listed templates: [[(url, record name)]]."""
        response = self.client.get(reverse("admin:inventory_locationlabeltemplate_changelist"), {"q": query})
        return [json.loads(html.unescape(data))
                for data in re.findall(r'data-label-samples="([^"]+)"', response.content.decode())]

    def test_list_samples_are_random_records_of_the_kind(self):
        samples = self.samples("descriptive_identifier")  # location templates showing the path
        self.assertTrue(samples)
        records = [name for _url, name in samples[0]]
        self.assertEqual(sorted(records), ["R303.a", "R303.b"])  # locations with a parent
        for sample in samples:  # the same for every template on the page
            self.assertEqual([name for _url, name in sample], records)
            response = self.client.get(sample[0][0])
            self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/png"))
        price, = {tuple(name for _url, name in sample) for sample in self.samples("Preis")}
        self.assertEqual(price, ("Schrauben M4",))

    def test_list_samples_only_of_records_the_template_is_meant_for(self):
        """By the template's rules: a price tag only for items with a price (Wechselstift has none)."""
        from inventory.models import Item, ItemLocation
        unpriced = Item.objects.create(name="Wechselstift", measurement_unit=self.unit)
        ItemLocation.objects.create(item=unpriced, location=self.part, amount=5)
        found = {}
        for query in ("Preis", "Artikel"):
            response = self.client.get(reverse("admin:inventory_locationlabeltemplate_changelist"), {"q": query})
            for name, data in re.findall(r'<a href="[^"]+">([^<]+)</a></th><td class="field-sample"><img [^>]*'
                                         r'data-label-samples="([^"]+)"', response.content.decode()):
                found.setdefault(name, set()).update(record for _url, record in json.loads(html.unescape(data)))
        self.assertEqual(found["Preisschild"], {"Schrauben M4"})
        self.assertEqual(found["Artikel"], {"Schrauben M4", "Wechselstift"})

    def test_preview_records_by_the_saved_rules(self):
        """While editing a saved template, its preview offers the records its saved rules are meant for."""
        from inventory.models import Item, ItemLocation
        unpriced = Item.objects.create(name="Wechselstift", measurement_unit=self.unit)
        ItemLocation.objects.create(item=unpriced, location=self.part, amount=5)
        price_tag = LocationLabelTemplate.objects.get(name="Preisschild", label_width=60, label_height=30)
        description = "label 60 x 30\ntext {{ item.name }}"
        records = lambda **data: self.client.post(reverse("label_design_preview"), {
            "description": description, "subject_type": "item", **data}).json()["records"]
        self.assertEqual(records(template=price_tag.pk), ["Schrauben M4"])
        self.assertEqual(records(), ["Wechselstift", "Schrauben M4"])  # a new template: the newest
        self.assertIn("Wechselstift", records(template=generated("item", "57x32").pk))  # kind == "bulk"

    def test_list_samples_only_of_records_one_may_see(self):
        viewer = create_user("viewer", "inventory.view_locationlabeltemplate")
        viewer.is_staff = True
        viewer.save()
        self.client.force_login(viewer)
        for sample in self.samples("Preis"):  # item labels: for who may print; else made up
            self.assertEqual(sample, [[sample[0][0], ""]])
            self.assertNotIn("record=", sample[0][0])
            self.assertEqual(self.client.get(sample[0][0]).status_code, 200)
        template = LocationLabelTemplate.objects.filter(subject_type="item").first()
        url = reverse("label_template_sample", args=[template.pk])
        self.assertEqual(self.client.get(url, {"record": self.item.pk}).status_code, 404)
        self.assertTrue(self.samples("descriptive_identifier")[0][0][1])  # location labels are public

    def test_preview_while_writing(self):
        url = reverse("label_design_preview")
        data = self.client.post(url, {"description": "label 57 x 32\ntext {{ location.unique_identifier }}  size 6", "subject_type": "location"}).json()
        self.assertTrue(data["image"].startswith("data:image/png;base64,"))
        self.assertEqual((data["problems"], data["size"]), ([], "456 × 256 dots at 203 dpi: 57.1 × 32.0 mm"))
        self.assertIn("R303.b", data["records"])
        data = self.client.post(url, {"description": "label height 12\ntext {{ location.unique_identifier }}\nfoo", "subject_type": "location"}).json()
        self.assertEqual(data["problems"][0]["line"], 3)
        self.assertIn(" × 150 dots at 360 dpi", data["size"])  # tape as a P900 prints it
        self.client.force_login(create_user("reader"))
        self.assertEqual(self.client.post(url, {"description": "label 10 x 10"}).status_code, 403)

    def test_template_form(self):
        add = reverse("admin:inventory_locationlabeltemplate_add")
        self.assertContains(self.client.get(add), "label 70 x 32")  # a starter description
        rules = {"rules-TOTAL_FORMS": "1", "rules-INITIAL_FORMS": "0", "rules-0-condition": "location.type.category ==",
                 "rules-0-priority": "2"}
        data = {"name": "Neu", "subject_type": "location", "quality": "standard", **rules,
                "description": "label 50 x 20\ntext '{% nope %}'"}
        response = self.client.post(add, data)
        self.assertContains(response, "Line 2: Invalid block tag: &#x27;nope&#x27;")
        self.assertContains(response, "Unexpected end of expression")  # the rule's condition
        data |= {"description": "label 50 x 20\ntext {{ location.unique_identifier }}",
                 "rules-0-condition": 'location.type.category == "container"'}
        self.client.post(add, data)
        template = LocationLabelTemplate.objects.get(name="Neu")
        self.assertEqual((template.label_width, template.label_height), (50, 20))
        self.assertEqual([str(rule) for rule in template.rules.all()], ['2: location.type.category == "container"'])
        # Material and colours as label stock names them, black on white unless chosen otherwise; empty: any
        self.assertEqual((template.print_color, template.background_color, template.material), ("schwarz", "weiß", ""))
        form = self.client.get(reverse("admin:inventory_locationlabeltemplate_change", args=[template.pk]))
        self.assertContains(form, '<option value="gelb">gelb</option>', html=True)
        self.assertContains(self.client.get(reverse("label_design_help")), "Label designs")

    def test_a_location_label_preview_is_public(self):
        """As the admin shows it (Location.label_image_tag); the location page shows none."""
        template = LocationLabelTemplate.objects.create(name="T", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        remember_label(self.part, template)  # printed with it last
        self.client.logout()
        url = self.part.label_preview_url()
        self.assertNotContains(self.client.get(self.part.get_absolute_url()), url)
        response = self.client.get(url)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (456, 256))
        item_url = reverse("label_template_preview", args=[template.pk, "item", self.item.pk])
        self.assertEqual(self.client.get(item_url).status_code, 404)  # not public


class TemplateCatalogTests(SimpleTestCase):
    """The templates label_printing 0002 brings (catalog/label_templates.json)."""

    def test_every_template_draws_without_mistakes(self):
        from label_printing.migrations import __path__ as migrations_path
        start = json.loads((Path(migrations_path[0]).parent / "catalog" / "label_templates.json").read_text())
        for entry in start:
            design, problems = parse(entry["description"])
            self.assertEqual(problems, [], entry["name"])
            self.assertEqual((design.width, design.height), (entry["label_width"], entry["label_height"]), entry["name"])
        # the location display rule: what a location is called first, its code after it
        card = next(entry["description"] for entry in start if entry["name"] == "Ort"
                    and entry["label_width"] == 57)
        self.assertLess(card.index("{{ location.title }}"), card.index("location.unique_identifier"))
        # the colour rule: locations and ZAMids on any colour (yellow: permanent places and things), items on white;
        # storage units and shelf levels printed inverted, white on black (70 × 32 mm paper, white tape; not yellow)
        colours = {}
        for entry in start:
            if entry["is_active"]:
                colours.setdefault(entry["subject_type"], set()).add((entry["print_color"], entry["background_color"]))
        self.assertEqual(colours, {"location": {("schwarz", ""), ("schwarz", "weiß")}, "labelid": {("schwarz", "")},
                                   "uniqueitem": {("schwarz", "")}, "item": {("schwarz", "weiß")}})
        inverted = {(entry["name"], entry["label_width"]) for entry in start
                    if entry["is_active"] and parse(entry["description"])[0].invert}
        shelves = {"Lagermöbel", "Regalboden, Pfeile zum Ausmalen", "Regalboden, Pfeil hoch", "Regalboden, Pfeil runter"}
        self.assertEqual(inverted, {(name, width) for name in shelves for width in (70, None)}
                         | {("Ort, Palettenregal", 105), ("Ort, Palettenregal", 100)})
        flags = sorted(entry["label_width"] for entry in start if entry["name"].startswith("Kabel, Fahne"))
        self.assertEqual(flags, [55, 57, 60, 62, 63])  # 2 × 17 mm and 2 to 1.5 times cables of 10.5 to 19 mm
        # cable wraps: about 1.2 times round the thickest cable of each class
        wraps = sorted(entry["label_width"] for entry in start if entry["name"].startswith("Kabel, Wickel"))
        self.assertEqual(wraps, [39.6, 45.1, 54.7, 64.1, 71.5])

    def test_logo_without_wordmark(self):
        """For small labels: the logo cut off at the first white row below the mark, above the wordmark."""
        import importlib
        migration = importlib.import_module("label_printing.migrations.0007_catalog_up_to_date")
        image = Image.new("1", (40, 20), 1)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 39, 11), fill=0)  # the mark, rows 0–11
        draw.rectangle((0, 15, 30, 18), fill=0)  # the wordmark, rows 15–18
        out = io.BytesIO()
        image.save(out, format="PNG")
        self.assertEqual(migration.wordmark_cut(out.getvalue()), 8)  # rows 12–19 cut off
        out = io.BytesIO()
        Image.new("1", (40, 20), 0).save(out, format="PNG")
        self.assertEqual(migration.wordmark_cut(out.getvalue()), 0)  # no gap: nothing to cut


class ZplTemplatesMigrationTests(TransactionTestCase):
    """From the inventory with ZPL templates (before label_printing): they become label designs, their logo a
    label image; label stock and the templates for every label are added (label_printing.0002)."""

    def test_zpl_templates_become_designs(self):
        before = [("inventory", "0041_admin_only_locks_purpose"), ("label_printing", None)]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before[:1]).apps
            Template = apps.get_model("inventory", "LocationLabelTemplate")
            mobile_zpl = Template.objects.create(name="105x52 mobile", label_width=105, label_height=52,
                                                 zpl_template="^XA^FO405,190^GFA,8,8,2,HFF0,\n,:FF00!^FS^FD$url^FS^XZ")
            own = Template.objects.create(name="Eigene", label_width=50, label_height=25,
                                          zpl_template="^XA^FD$url^FS^XZ")
            room = apps.get_model("inventory", "LocationType").objects.create(name="Raum", unique=True,
                                                                              default_label_template=mobile_zpl)
            Location = apps.get_model("inventory", "Location")
            hall = Location.objects.create(name="Halle", short_name="HAL", type=room, label_template=own,
                                           unique_identifier="HAL", locatable_identifier="HAL",
                                           descriptive_identifier="Halle [HAL]")
            room_2 = Location.objects.create(name="Raum 2", short_name="R2", type=room, unique_identifier="R2",
                                             locatable_identifier="R2", descriptive_identifier="Raum 2 [R2]")
            with override_settings(MEDIA_ROOT=media):
                executor = MigrationExecutor(connection)
                executor.migrate(latest)
                apps = executor.loader.project_state(latest).apps
                Template = apps.get_model("inventory", "LocationLabelTemplate")
                mobile = Template.objects.get(name="Kiste", label_width=105)
                own = Template.objects.get(name="Eigene")
                self.assertIn('image "ZAM Logo"', mobile.description)
                self.assertEqual(parse(mobile.description)[1], [])
                self.assertTrue(own.description.startswith("# Converted from a ZPL template"))
                self.assertIn("# ^XA^FD$url^FS^XZ", own.description)
                self.assertEqual((parse(own.description)[0].width, parse(own.description)[0].height), (50, 25))
                self.assertTrue(Template.objects.filter(name="ZAMid", label_width=70, subject_type="labelid").exists())
                # those of the development server (the ZPL template it replaces kept as it was), and the unknown one
                from label_printing.migrations import __path__ as migrations_path
                start = json.loads((Path(migrations_path[0]).parent / "catalog" / "label_templates.json").read_text())
                self.assertEqual(Template.objects.count(), len(start) + 1)
                self.assertEqual(mobile.pk, mobile_zpl.pk)
                self.assertEqual(mobile.description, next(entry["description"] for entry in start
                                                          if entry["name"] == mobile.name and entry["label_width"] == 105))
                item_9 = Template.objects.get(name="Artikel", label_height=9)
                self.assertFalse(item_9.is_active)
                rules = apps.get_model("inventory", "LabelTemplateRule").objects
                self.assertEqual(list(rules.filter(template=mobile).values_list("condition", "priority")),
                                 [('location.type.name == "Kiste"', 3), ("", 0)])
                self.assertEqual(list(rules.filter(template=own).values_list("condition", "priority")), [("", 0)])
                # the template chosen for the location: preselected as its last label
                last = apps.get_model("label_printing", "LastLabel").objects
                self.assertEqual(last.get(subject_type="location", subject_pk=str(hall.pk)).layout_key, f"design:{own.pk}")
                # else its type's
                self.assertEqual(last.get(subject_type="location", subject_pk=str(room_2.pk)).layout_key,
                                 f"design:{mobile.pk}")
                stock = apps.get_model("label_printing", "LabelStock")
                # one per size of the ZPL templates ("Etikett …"; later migrations add labels bought since)
                self.assertEqual(sorted(stock.objects.filter(language="zpl", name__startswith="Etikett ")
                                        .values_list("name", flat=True)),
                                 ["Etikett 105 × 52 mm Polyester", "Etikett 50 × 25 mm"])
                self.assertTrue(stock.objects.filter(language="ptouch").exists())
                self.assertTrue(apps.get_model("auth", "Group").objects.get(name="ZAM-local").permissions.filter(
                    codename="print_label").exists())
                logo = apps.get_model("label_printing", "LabelImage").objects.get(name="ZAM Logo")
                with Image.open(logo.image.path) as image:
                    self.assertEqual(image.size, (16, 4))
                    self.assertEqual([image.getpixel((x, 0)) for x in (0, 11, 12)], [0, 0, 255])  # FFF0
                # nothing below the mark: the logo without wordmark is the whole logo (wordmark_cut)
                mark = apps.get_model("label_printing", "LabelImage").objects.get(name="ZAM Logo ohne Wortmarke")
                self.assertEqual((mark.image.name, mark.crop_bottom), (logo.image.name, 0))
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
