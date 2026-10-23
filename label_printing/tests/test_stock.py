import importlib
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from inventory.models import Location, LocationLabelTemplate, LocationType
from ..layouts import layouts_for
from ..models import LabelMedium, LabelStock
from .helpers import SETTINGS, create_printers, create_user

stock_data = importlib.import_module("label_printing.migrations.0004_label_stock_data")


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

    def test_zebra_stock_from_the_templates(self):
        small = LocationLabelTemplate.objects.create(name="70x32 static", zpl_template="^XA^XZ", label_width=70, label_height=32)
        down = LocationLabelTemplate.objects.create(name="70x32 down", zpl_template="^XA^XZ", label_width=70, label_height=32)
        box = LocationLabelTemplate.objects.create(name="105x52 mobile", zpl_template="^XA^XZ", label_width=105, label_height=52)
        LocationLabelTemplate.objects.create(name="other", zpl_template="^XA^XZ", label_width=50, label_height=25)
        stock_data.zebra_labels_of_templates(apps, SimpleNamespace(connection=connection))
        stocks = {stock.name: stock for stock in LabelStock.objects.filter(language="zpl")}
        self.assertEqual(set(stocks), {"Etikett 70 × 32 mm Papier", "Etikett 105 × 52 mm Polyester", "Etikett 50 × 25 mm"})
        paper, polyester = stocks["Etikett 70 × 32 mm Papier"], stocks["Etikett 105 × 52 mm Polyester"]
        self.assertEqual(set(paper.zpl_templates.all()), {small, down})
        self.assertEqual(list(polyester.zpl_templates.all()), [box])
        self.assertEqual((paper.method, paper.ribbon, paper.material), ("transfer", "wax", "Papier"))
        self.assertEqual((polyester.method, polyester.ribbon, polyester.material), ("transfer", "resin", "Polyester"))
        self.assertEqual(stocks["Etikett 50 × 25 mm"].method, "")  # other sizes: not known
        for stock in stocks.values():
            stock.full_clean()

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
        template = LocationLabelTemplate.objects.create(name="Fach", zpl_template="^XA^XZ", label_width=57, label_height=32)
        stock = LabelStock.objects.create(language="zpl", name="57 × 32", width_mm=57, height_mm=32, method="direct")
        stock.zpl_templates.add(template)
        labels.stock = stock
        labels.save()
        self.assertIn(f"zpl:{template.pk}", [layout.key for layout in layouts_for("location", zebra, labels)])
        other = LocationLabelTemplate.objects.create(name="Own", zpl_template="^XA^XZ", label_width=57, label_height=32)
        labels.zpl_templates.add(other)  # the medium's own choice wins
        self.assertEqual([layout.key for layout in layouts_for("location", zebra, labels)][:1], [f"zpl:{other.pk}"])
        self.assertNotIn(f"zpl:{template.pk}", [layout.key for layout in layouts_for("location", zebra, labels)])

    def test_preview_in_the_tape_colours(self):
        _zebra, _labels, brother, tape = create_printers()
        tape.stock = LabelStock.objects.get(code="TZe-631")  # black on yellow
        tape.save()
        location = Location.objects.create(name="Lager", short_name="WH", type=LocationType.objects.create(name="Room", unique=True))
        self.client.force_login(create_user("p", "label_printing.print_label"))
        response = self.client.get(reverse("print_preview", args=["location", location.pk]),
                                   {"medium": tape.pk, "layout": "location"})
        image = Image.open(BytesIO(response.content)).convert("RGB")
        self.assertEqual(image.getpixel((image.width - 1, 0)), (255, 212, 0))
        self.assertIn("Standard, laminiert", self.client.get(location.get_absolute_url()).content.decode())
