from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from inventory.models import Location, LocationLabelTemplate, LocationType
from ..layouts import layouts_for
from ..models import LabelMedium, LabelStock
from .helpers import SETTINGS, create_printers, create_user, generated


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

    def test_medium_from_stock(self):
        zebra, _labels, brother, _tape = create_printers()
        tape = LabelMedium(printer=brother, stock=LabelStock.objects.get(code="TZe-S241"))
        tape.full_clean()
        tape.save()
        self.assertEqual((tape.name, tape.ptouch_tape), (str(tape.stock), 18))
        with self.assertRaises(ValidationError) as raised:
            LabelMedium(printer=zebra, stock=tape.stock).full_clean()
        self.assertIn("stock", raised.exception.message_dict)

    def test_templates_of_the_stock_are_offered(self):
        zebra, labels, *_ = create_printers()
        def template(name):
            return LocationLabelTemplate.objects.create(name=name, description="label 57 x 32\ntext {{ location.unique_identifier }}")
        chosen, other = template("Fach"), template("Anderes")
        keys = lambda: [layout.key for layout in layouts_for("location", zebra, labels)]
        self.assertIn(f"design:{other.pk}", keys())  # nothing chosen: every template of the size
        stock = LabelStock.objects.create(language="zpl", name="57 × 32", width_mm=57, height_mm=32, method="direct")
        stock.label_templates.add(chosen)
        labels.stock = stock
        labels.save()
        self.assertIn(f"design:{chosen.pk}", keys())
        self.assertNotIn(f"design:{other.pk}", keys())
        own = template("Own")
        labels.label_templates.add(own)  # the medium's own choice wins
        self.assertEqual(keys()[:1], [f"design:{own.pk}"])
        self.assertNotIn(f"design:{chosen.pk}", keys())

    def test_preview_in_the_tape_colours(self):
        _zebra, _labels, brother, tape = create_printers()
        tape.stock = LabelStock.objects.get(code="TZe-631")  # black on yellow
        tape.save()
        location = Location.objects.create(name="Lager", short_name="WH", type=LocationType.objects.create(name="Room", unique=True))
        self.client.force_login(create_user("p", "label_printing.print_label"))
        response = self.client.get(reverse("print_preview", args=["location", location.pk]),
                                   {"medium": tape.pk, "layout": f"design:{generated('location', 'tape12').pk}"})
        image = Image.open(BytesIO(response.content)).convert("RGB")
        self.assertEqual(image.getpixel((image.width - 1, 0)), (255, 212, 0))
