"""Label designs: the description language, the layout, and label templates in printing and the admin."""
import io
import shutil
import tempfile
import zipfile
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
from ..design import Context, Problem, check, parse, render_design
from ..label_urls import ItemAt
from ..image_import import import_images
from ..layouts import get_layout, layouts_for
from ..models import LabelImage
from .helpers import GENERATED, SETTINGS, create_printers, create_user, generated
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
            (3, "“imgae” is not an element. Did you mean “image”? Elements: row, column, text, qr, image, box, line, "
                "arrow, space."),
            (4, "text needs its content first: text in quotes or a {{ variable }}."),
            (5, "“ecc” is one of L, M, Q, H, not “X”."),
            (7, "Only row and column hold indented elements."),
            (8, "“x” is not a length in mm."),
            (9, "A quote is not closed."),
        ])
        self.assertEqual(parse("text {{ code }}")[1][0].line, 1)  # the size first

    def test_template_syntax_and_unknown_images(self):
        design, _problems = parse('label 50 x 20\ntext {{ code }}\ntext "{% if code %}x{% endfi %}"\nimage "Logo"')
        self.assertEqual([(problem.line, problem.message) for problem in check(design, set())], [
            (3, "Invalid block tag: 'endfi', expected 'elif', 'else' or 'endif'. Did you forget to register or "
                "load this tag?"),
            (4, "There is no label image “Logo”.")])
        self.assertEqual(parse("label 50 x 20\ntext {code}")[1][0].message,
                         "text needs its content first: text in quotes or a {{ variable }}.")  # the fields of before

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

    def test_text_crowded_out_is_a_problem_not_an_error(self):
        _image, problems = draw("label height 9  margin 1\ncolumn\n  text {{ code }}  invert\n  text {{ path }}  size 7",
                                {"code": "A1", "path": "Raum / Regal"})
        self.assertEqual([(problem.line, problem.message) for problem in problems],
                         [(3, "There is no room left for this text.")])


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
                         (57, 32, None, "height 12 mm, any length"))
        keys = lambda printer, medium: [layout.key for layout in layouts_for("location", printer, medium)]
        self.assertIn(f"design:{fixed.pk}", keys(self.zebra, self.labels))
        self.assertNotIn(f"design:{tape.pk}", keys(self.zebra, self.labels))
        self.assertIn(f"design:{tape.pk}", keys(self.brother, self.tape))
        self.assertNotIn(f"design:{wide.pk}", keys(self.brother, self.tape))
        self.assertNotIn(f"design:{fixed.pk}", keys(self.brother, self.tape))

    def test_printed_on_matching_labels_only(self):
        from ..layouts.designs import fits
        from ..models import LabelMedium
        fixed = self.template("label 57 x 32\ntext {{ location.unique_identifier }}")
        endless = self.template("label height 12\ntext {{ location.unique_identifier }}")
        long_tape = self.template("label 40 x 12\ntext {{ location.unique_identifier }}")
        narrow = self.template("label height 3.5\ntext {{ location.unique_identifier }}")
        unknown = LabelMedium(printer=self.zebra, name="?")
        self.assertFalse(fits(fixed, unknown))  # labels of unknown size match no template
        self.assertTrue(fits(fixed, LabelMedium(printer=self.zebra, name="a", width_mm=58, height_mm=32)))
        self.assertFalse(fits(fixed, LabelMedium(printer=self.zebra, name="b", width_mm=57, height_mm=25)))
        cut = LabelMedium(printer=self.brother, name="12 mm, 40 mm long", ptouch_tape=12, height_mm=40)
        self.assertEqual((fits(endless, self.tape), fits(long_tape, self.tape)), (True, True))  # endless tape
        self.assertEqual((fits(endless, cut), fits(long_tape, cut)), (False, True))
        self.assertTrue(fits(narrow, LabelMedium(printer=self.brother, name="3.5 mm", ptouch_tape=4)))
        with self.assertRaisesMessage(services.PrintError, "This layout does not fit"):
            services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{endless.pk}",
                            subject_type="location", subjects=[self.part])

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

    def test_price_tags(self):
        from inventory.models import LocationLabelTemplate as Template
        from ..models import LabelMedium
        card = LabelMedium.objects.create(printer=self.zebra, name="60 × 30", width_mm=60, height_mm=30)
        tapes = {width: LabelMedium.objects.create(printer=self.brother, name=f"{width} mm", ptouch_tape=width)
                 for width in (18, 24)}
        tapes[12] = self.tape
        price_tags = [((60, 30), card)] + [((None, width), tapes[width]) for width in (12, 18, 24)]
        for (width, height), medium in price_tags:
            template = Template.objects.get(name="Preisschild", label_width=width, label_height=height)
            self.assertIn(f"design:{template.pk}", [layout.key for layout in layouts_for("item", medium.printer, medium)])
            rendered, = services.render(get_layout(f"design:{template.pk}"), [ItemAt(self.item, self.part)], medium,
                                        preview=True)
            self.assertEqual(rendered.snapshot["price"], "0.15 € / Stk")
        self.assertEqual(rendered.image.height, 128)  # E550W, 24 mm tape

    def test_templates_for_every_label(self):
        """The migrations' templates: each kind for the Zebra labels in use and every Brother tape width."""
        from ..layouts.designs import problems_of
        from ..models import LabelMedium, Printer
        p900 = Printer.objects.create(name="P900W", slug="p900", language="ptouch", model="P900W", dpi=360,
                                      host="127.0.0.1")
        media = {f"tape{width}": LabelMedium.objects.create(printer=p900, name=f"{width} mm", ptouch_tape=width)
                 for width in (9, 12, 18, 24, 36)}
        media |= {f"{width}x{height}": LabelMedium.objects.create(printer=self.zebra, name=f"{width}x{height}",
                                                                  width_mm=width, height_mm=height)
                  for width, height in ((57, 32), (60, 30), (70, 32), (105, 52))}
        for kind in GENERATED:
            for size, medium in media.items():
                with self.subTest(kind=kind, size=size):
                    template = generated(kind, size)
                    self.assertEqual(problems_of(template)[1], [])
                    self.assertIn(f"design:{template.pk}", [layout.key for layout in
                                                            layouts_for(template.subject_type, medium.printer, medium)])

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
        response = self.client.post(add, {"name": "Neu", "subject_type": "location", "quality": "standard", "description": "label 50 x 20\ntext '{% nope %}'"})
        self.assertContains(response, "Line 2: Invalid block tag: &#x27;nope&#x27;")
        self.client.post(add, {"name": "Neu", "subject_type": "location", "quality": "standard", "description": "label 50 x 20\ntext {{ location.unique_identifier }}"})
        template = LocationLabelTemplate.objects.get(name="Neu")
        self.assertEqual((template.label_width, template.label_height), (50, 20))
        self.assertContains(self.client.get(reverse("label_design_help")), "Label designs")

    def test_location_page_shows_its_label(self):
        template = LocationLabelTemplate.objects.create(name="T", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        self.part.label_template = template
        self.part.save()
        self.client.logout()
        url = self.part.label_preview_url()
        self.assertContains(self.client.get(self.part.get_absolute_url()), url)
        response = self.client.get(url)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (456, 256))
        item_url = reverse("label_template_preview", args=[template.pk, "item", self.item.pk])
        self.assertEqual(self.client.get(item_url).status_code, 404)  # not public


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
            Template.objects.create(name="105x52 mobile", label_width=105, label_height=52,
                                    zpl_template="^XA^FO405,190^GFA,8,8,2,HFF0,\n,:FF00!^FS^FD$url^FS^XZ")
            Template.objects.create(name="Eigene", label_width=50, label_height=25, zpl_template="^XA^FD$url^FS^XZ")
            with override_settings(MEDIA_ROOT=media):
                executor = MigrationExecutor(connection)
                executor.migrate(latest)
                apps = executor.loader.project_state(latest).apps
                Template = apps.get_model("inventory", "LocationLabelTemplate")
                mobile, own = Template.objects.get(name="Mobil, mit Logo und Eigentum"), Template.objects.get(name="Eigene")
                self.assertIn('image "ZAM Logo"', mobile.description)
                self.assertEqual(parse(mobile.description)[1], [])
                self.assertTrue(own.description.startswith("# Converted from a ZPL template"))
                self.assertIn("# ^XA^FD$url^FS^XZ", own.description)
                self.assertEqual((parse(own.description)[0].width, parse(own.description)[0].height), (50, 25))
                self.assertTrue(Template.objects.filter(name="ZAMid", label_width=70, subject_type="labelid").exists())
                self.assertEqual(Template.objects.count(), 2 + 4 * 9 + 4)  # converted, for every label, price tags
                stock = apps.get_model("label_printing", "LabelStock")
                self.assertEqual(sorted(stock.objects.filter(language="zpl").values_list("name", flat=True)),
                                 ["Etikett 105 × 52 mm Polyester", "Etikett 50 × 25 mm"])
                self.assertTrue(stock.objects.filter(language="ptouch").exists())
                self.assertTrue(apps.get_model("auth", "Group").objects.get(name="ZAM-local").permissions.filter(
                    codename="print_label").exists())
                logo = apps.get_model("label_printing", "LabelImage").objects.get(name="ZAM Logo")
                with Image.open(logo.image.path) as image:
                    self.assertEqual(image.size, (16, 4))
                    self.assertEqual([image.getpixel((x, 0)) for x in (0, 11, 12)], [0, 0, 255])  # FFF0
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
