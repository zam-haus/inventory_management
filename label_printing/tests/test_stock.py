from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from inventory.models import Location, LocationLabelTemplate, LocationType
from ..layouts import layouts_for
from ..models import LabelStock, Medium
from .helpers import SETTINGS, create_printers, create_user, generated, labels


@override_settings(**SETTINGS)
class LabelStockTests(TestCase):
    def test_brother_tapes_come_with_colours(self):
        tape = LabelStock.objects.get(code="TZe-231")
        self.assertEqual((tape.language, tape.tape_mm, tape.print_color, tape.background_color, tape.length_m),
                         ("ptouch", 12, "schwarz", "weiß", Decimal("8.00")))
        self.assertEqual(tape.description_short, "Standard, laminiert")
        self.assertEqual(str(tape), "TZe-231 12 mm schwarz on weiß (Standard, laminiert)")
        self.assertEqual(LabelStock.objects.get(code="TZe-S251").description_short, "Extra-stark klebend, laminiert")
        self.assertEqual(LabelStock.objects.get(code="TZe-N201").tape_mm, 4)  # 3.5 mm tape
        self.assertFalse(LabelStock.objects.filter(code__startswith="HSe-").exists())
        self.assertGreater(LabelStock.objects.filter(language="ptouch").count(), 100)

    def test_the_likeliest_tape_a_brother_reported(self):
        """A Brother reports width, colours and kind of its tape, not the article: of those that fit, the one on
        hand first, else the standard tape."""
        from ..models import Printer
        printer = Printer.objects.create(name="P900W", slug="p900w", language="ptouch", model="P900W", dpi=360)
        printer.remember_status({"media_width_mm": 12, "tape_color": "weiß", "text_color": "schwarz",
                                 "media_type": "laminated"})

        def codes():
            return [LabelStock.objects.get(pk=pk).code for pk in printer.loaded_stock_ids()]
        self.assertEqual(codes()[0], "TZe-231")
        self.assertNotIn("TZe-N231", codes())  # not laminated
        self.assertNotIn("TZe-R231", codes())  # fabric, reported as such
        LabelStock.objects.filter(code="TZe-S231").update(in_stock=True)
        self.assertEqual(codes()[0], "TZe-S231")
        printer.remember_status({"media_width_mm": 12, "tape_color": "weiß", "text_color": "schwarz",
                                 "media_type": "non_laminated"})
        self.assertEqual(codes(), ["TZe-N231"])

    def test_zebra_printing_method_and_ribbon(self):
        stock = LabelStock(language="zpl", name="Polyester", width_mm=50, height_mm=25, method="transfer")
        with self.assertRaises(ValidationError) as raised:
            stock.clean()
        self.assertIn("ribbon", raised.exception.message_dict)
        stock.ribbon = "resin"
        stock.material = "Polyester"
        stock.clean()
        self.assertEqual(stock.method_text, "thermal transfer, resin ribbon")
        with self.assertRaises(ValidationError):
            LabelStock(language="zpl", name="Paper", width_mm=50, height_mm=25, method="direct", ribbon="wax").clean()

    def test_medium_of_label_material(self):
        zebra, _labels, brother, _tape = create_printers()
        stock = LabelStock.objects.get(code="TZe-S241")
        tape = labels(brother, stock=stock)
        self.assertEqual((tape.name, tape.ptouch_tape, tape.width_mm), (stock.name, 18, None))
        self.assertNotIn(tape, brother.media())  # not on hand
        LabelStock.objects.filter(pk=stock.pk).update(in_stock=True)
        self.assertIn(tape, brother.media())
        self.assertEqual(zebra.takes(stock), "These labels are for another kind of printer.")

    def test_loaded_material_is_printed_on_without_being_on_hand(self):
        zebra, zebra_labels, brother, _tape = create_printers()
        LabelStock.objects.update(in_stock=False)
        self.assertEqual(zebra.media(), [zebra_labels])  # set as loaded
        self.assertEqual(brother.media(), [])
        brother.remember_status({"media_width_mm": 18, "tape_color": "gelb", "text_color": "schwarz"})
        loaded = {medium.stock for medium in brother.media()}
        self.assertTrue(loaded)
        self.assertEqual({(stock.tape_mm, stock.background_color, stock.print_color) for stock in loaded},
                         {(18, "gelb", "schwarz")})
        brother.remember_status({"media_width_mm": 18, "tape_color": "andere", "text_color": "andere"})
        self.assertEqual(len(brother.media()), LabelStock.objects.filter(language="ptouch", tape_mm=18).count())

    def test_templates_by_label_stock_material_and_colours(self):
        """A template prints on labels of its size, and of its label stock, material and colours if it names them;
        label stock without colours is black on white."""
        zebra, labels, brother, tape = create_printers()
        LocationLabelTemplate.objects.update(is_active=False)

        def template(name, size="57 x 32", **criteria):
            return LocationLabelTemplate.objects.create(name=name, description=f"label {size}\ntext {{{{ qr }}}}",
                                                        **criteria)
        plain, any_colour = template("Schlicht"), template("Beliebig", print_color="", background_color="")
        yellow = template("Gelb", background_color="gelb")
        paper = template("Papier", material="papier")
        paper_stock = LabelStock.objects.create(language="zpl", name="57 × 32 Papier", width_mm=57, height_mm=32,
                                                material="Papier")
        own = template("Eigene", label_stock=paper_stock)
        keys = lambda printer, medium: {layout.template for layout in layouts_for("location", printer, medium)}
        self.assertEqual(keys(zebra, labels), {plain, any_colour})  # without stock: black on white, material unknown
        self.assertEqual(keys(zebra, Medium(zebra, paper_stock)), {plain, any_colour, paper, own})
        on_tape = [template(name, size="height 12", **criteria) for name, criteria in (
            ("Schlicht", {}), ("Beliebig", {"print_color": "", "background_color": ""}),
            ("Gelb", {"background_color": "gelb"}))]
        black_on_yellow = Medium(brother, LabelStock.objects.get(code="TZe-631"))
        self.assertEqual(keys(brother, black_on_yellow), set(on_tape[1:]))

    def test_preview_in_the_tape_colours(self):
        _zebra, _labels, brother, tape = create_printers()
        LocationLabelTemplate.objects.filter(pk=generated("location", "tape12").pk).update(background_color="")
        black_on_yellow = LabelStock.objects.get(code="TZe-631")
        location = Location.objects.create(name="Lager", short_name="WH", type=LocationType.objects.create(name="Room", unique=True))
        self.client.force_login(create_user("p", "label_printing.print_label"))
        response = self.client.get(reverse("print_preview", args=["location", location.pk]),
                                   {"medium": f"{brother.pk}:{black_on_yellow.pk}",
                                    "layout": f"design:{generated('location', 'tape12').pk}"})
        image = Image.open(BytesIO(response.content)).convert("RGB")
        self.assertEqual(image.getpixel((image.width - 1, 0)), (255, 212, 0))
