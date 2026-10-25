from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from inventory.numbered_location_views import with_print_dialog
from inventory.models import Item, ItemLocation, LabelId, Location, LocationLabelTemplate, LocationType, MeasurementUnit
from .. import dialog, drivers, label_urls, services, simulator
from ..layouts import Canvas, get_layout, layouts_for
from ..models import LabelMedium, PrintJob
from .helpers import SETTINGS, SimulatedPrinters, create_printers, create_user, generated, outcome_key


class InventoryData:
    @classmethod
    def create_inventory(cls):
        cls.unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Stück", "short": "Stk"})
        room = LocationType.objects.create(name="Room", unique=True)
        compartment = LocationType.objects.create(name="Compartment")
        cls.shelf = Location.objects.create(name="Regal 303", short_name="R303", type=room)
        cls.part = Location.objects.create(name="Fach a", short_name="a", type=compartment, parent_location=cls.shelf)
        cls.other_part = Location.objects.create(name="Fach b", short_name="b", type=compartment, parent_location=cls.shelf)
        cls.item = Item.objects.create(name="Schrauben M4", measurement_unit=cls.unit, for_sale=True,
                                       sale_price=Decimal("0.15"))
        ItemLocation.objects.create(item=cls.item, location=cls.part, amount=100)
        ItemLocation.objects.create(item=cls.item, location=cls.other_part, amount=20)


@override_settings(**SETTINGS)
class LayoutTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()

    def layout(self, kind, size):
        return get_layout(f"design:{generated(kind, size).pk}")

    def test_labels_fill_the_medium(self):
        for medium, size in ((self.labels, "57x32"), (self.tape, "tape12")):
            canvas = Canvas.for_medium(medium)
            for kind, subject in (("location", self.part), ("item", label_urls.ItemAt(self.item, self.part))):
                with self.subTest(medium=medium.name, kind=kind):
                    image = self.layout(kind, size).render(subject, canvas, medium, preview=True).image
                    self.assertEqual(image.height, canvas.height)
                    if canvas.width:
                        self.assertEqual(image.width, canvas.width)

    def test_labels_too_small_for_a_qr_code_are_not_offered(self):
        tape = LabelMedium.objects.create(printer=self.brother, name="9 mm", ptouch_tape=9)
        layout = self.layout("labelid", "tape9")
        self.assertFalse(layout.supports(self.brother, tape))  # 180 dpi: too few dots per module
        self.assertNotIn(layout.key, [found.key for found in layouts_for("labelid", self.brother, tape)])
        self.brother.model, self.brother.dpi = "P900W", 360
        self.assertTrue(layout.supports(self.brother, tape))

    def test_location_label_holds_its_code(self):
        rendered = self.layout("location", "57x32").render(self.part, Canvas.for_medium(self.labels), self.labels)
        self.assertEqual(rendered.label_code, "R303.a")
        self.assertEqual(rendered.snapshot["qr"], "HTTPS://I.ZAM.HAUS/R303.A")

    def test_item_label_gets_a_label_id_once(self):
        subject = label_urls.ItemAt(self.item, self.part)
        canvas = Canvas.for_medium(self.labels)
        layout = self.layout("item", "57x32")
        preview = layout.render(subject, canvas, self.labels, preview=True)
        self.assertEqual((preview.label_code, LabelId.objects.count()), (label_urls.PREVIEW_CODE, 0))
        first = layout.render(subject, canvas, self.labels)
        again = layout.render(subject, canvas, self.labels)
        lid = LabelId.objects.get()
        self.assertEqual((first.label_code, again.label_code), (lid.code, lid.code))
        self.assertEqual((lid.item, lid.url or "", lid.batch), (self.item, "", "print"))  # the item's own ID
        self.assertEqual(first.snapshot["price"], "0.15 € / Stk")
        self.assertEqual(first.snapshot["qr"], f"HTTPS://I.ZAM.HAUS/{lid.code}/R303.A")  # alphanumeric
        # Another location: the same ID, with that location
        other = layout.render(label_urls.ItemAt(self.item, self.other_part), canvas, self.labels)
        self.assertEqual((LabelId.objects.count(), other.label_code), (1, lid.code))
        self.assertEqual(other.snapshot["qr"], f"HTTPS://I.ZAM.HAUS/{lid.code}/R303.B")
        without = layout.render(label_urls.ItemAt(self.item, None), canvas, self.labels)
        self.assertEqual(without.snapshot["qr"], f"HTTPS://I.ZAM.HAUS/{lid.code}")

    def test_zebra_raster_size(self):
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=f"design:{generated('location', '57x32').pk}",
                              subject_type="location", subjects=[self.part])
        self.assertIn(f"^PW{drivers.mm_to_dots(57, 203)}^LL{drivers.mm_to_dots(32, 203)}", bytes(job.payload).decode())


@override_settings(**SETTINGS)
class PrintDialogTests(SimulatedPrinters, InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers(cls.zebra_server.port, cls.brother_server.port)
        cls.template = LocationLabelTemplate.objects.create(name="Fach", description="label 57 x 32\nqr {{ qr }}")
        cls.labels.label_templates.add(cls.template)
        cls.user = create_user("printing", "label_printing.print_label", "inventory.add_stockchange")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post(self, subject_type, obj, data, json=True):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("print_labels", args=[subject_type, obj.pk]), data,
                                        headers={"Accept": "application/json"} if json else {})
        return response

    def test_location_page_offers_the_dialog(self):
        response = self.client.get(self.shelf.get_absolute_url())
        self.assertContains(response, 'data-modal-open="label-print-modal-location"')
        self.assertContains(response, 'id="label-print-modal-location"')
        self.assertContains(response, '"printer": "Zebra Lager"')
        self.assertContains(response, f'"key": "design:{self.template.pk}@57x32"')
        self.assertContains(response, f'"key": "{outcome_key("location", "tape12")}"')
        self.assertContains(response, "Also its sub-locations (2)")
        self.assertContains(response, "data-wait-note hidden")  # what waiting means, for labels no printer can print now
        self.assertNotContains(response, 'name="wait"')

    def test_print_a_location_and_its_compartments(self):
        response = self.post("location", self.shelf, {"outcome": outcome_key("location", "tape12"), "copies": 1,
                                                      "children": "on",
                                                      "request_id": str(uuid4())})
        data = response.json()
        self.assertTrue(data["ok"], data)
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.pages, job.user, job.subject_type), (3, self.user, "location"))
        self.assertEqual([entry["code"] for entry in job.snapshot], ["R303", "R303.a", "R303.b"])
        self.assertEqual(len(self.brother_output.printed), 3)
        status = self.client.get(reverse("print_job_status", args=[job.pk])).json()
        self.assertEqual((status["status"], status["message"]), ("done", "printed"))

    def test_print_an_item_label(self):
        data = self.post("item", self.item, {"outcome": outcome_key("item", "57x32"), "copies": 2,
                                             "location": self.part.pk}).json()
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.subject_type, job.subject_id, job.copies, job.quality),
                         ("item", self.item.pk, 2, "standard"))  # the template's quality
        self.assertEqual(job.snapshot[0]["location"], "R303.a")
        self.assertEqual(job.label_code, LabelId.objects.get().code)
        # The dialog says the QR code holds the item's label ID now, with the location chosen
        options = dialog.options("item", self.item)
        self.assertEqual(options["label_id"], LabelId.objects.get().display)
        self.assertEqual([entry["code"] for entry in options["locations"]], ["R303.a", "R303.b"])

    def test_price_tags_of_the_bulk_items_at_a_location(self):
        nuts = Item.objects.create(name="Muttern M4", measurement_unit=self.unit, for_sale=True, sale_price=Decimal("0.05"))
        ItemLocation.objects.create(item=nuts, location=self.part, amount=50)
        response = self.client.get(self.part.get_absolute_url())
        self.assertContains(response, 'id="label-print-modal-items"')
        self.assertContains(response, "A price tag for each of the 2 bulk items stored here.")
        key = outcome_key("item", "57x32")
        preview = self.client.get(reverse("print_preview", args=["items", self.part.pk]),
                                  {"medium": self.labels.pk, "layout": key.split("@")[0]})
        self.assertEqual(preview["Content-Type"], "image/png")
        data = self.post("items", self.part, {"outcome": key, "copies": 1}).json()
        job = PrintJob.objects.get(pk=data["job"]["id"])
        self.assertEqual((job.subject_type, job.pages), ("item", 2))
        self.assertEqual([(entry["name"], entry["location"]) for entry in job.snapshot],
                         [("Muttern M4", "R303.a"), ("Schrauben M4", "R303.a")])
        # Only those with a sale price
        ItemLocation.objects.create(item=Item.objects.create(name="Kabelbinder", measurement_unit=self.unit),
                                    location=self.part, amount=10)
        data = self.post("items", self.part, {"outcome": key, "copies": 1, "priced": "on"}).json()
        names = [entry["name"] for entry in PrintJob.objects.get(pk=data["job"]["id"]).snapshot]
        self.assertEqual(names, ["Muttern M4", "Schrauben M4"])
        self.assertEqual(dialog.options("items", self.part)["priced"], 2)
        # Where no bulk items are stored, the button says so
        self.assertContains(self.client.get(self.shelf.get_absolute_url()), "No bulk items are stored here.")

    def test_many_labels_are_confirmed_and_at_most_50(self):
        key = outcome_key("location", "tape12")
        response = self.post("location", self.part, {"outcome": key, "copies": 11})
        self.assertEqual(response.json()["errors"]["confirm"][0],
                         {"message": "That is 11 labels. Print them all?", "code": "confirm"})
        response = self.post("location", self.shelf, {"outcome": key, "copies": 20, "children": "on", "confirm": "on"})
        self.assertEqual(response.json()["errors"]["copies"][0]["message"],
                         "That would be 60 labels; at most 50 can be printed at once.")
        self.assertFalse(PrintJob.objects.exists())
        with patch("label_printing.tasks.process_job.delay"):
            response = self.post("location", self.part, {"outcome": key, "copies": 11, "confirm": "on"})
        self.assertEqual(PrintJob.objects.get(pk=response.json()["job"]["id"]).pages, 11)

    def test_errors_are_shown_in_the_dialog(self):
        cases = [
            ({"outcome": outcome_key("location", "tape24"), "copies": 1}, "outcome"),
            ({"outcome": outcome_key("item", "57x32"), "copies": 1}, "outcome"),
            ({"outcome": f"design:{self.template.pk}@57x32", "copies": 99}, "copies"),
        ]
        for data, field in cases:
            with self.subTest(field=field):
                response = self.post("location", self.part, data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
        self.assertFalse(PrintJob.objects.exists())

    def test_printer_errors_come_back_with_the_job(self):
        self.brother_state.tape_mm = 24
        data = self.post("location", self.part, {"outcome": outcome_key("location", "tape12"), "copies": 1}).json()
        # In the test's transaction the job starts after the answer; the dialog then follows it.
        status = self.client.get(reverse("print_job_status", args=[data["job"]["id"]])).json()
        self.assertEqual((status["status"], status["message"]), ("failed", "24 mm tape is loaded, but 12 mm was chosen."))

    def test_fallback_page_without_javascript(self):
        response = self.client.get(reverse("print_labels", args=["location", self.part.pk]))
        self.assertContains(response, "Print labels")
        self.assertContains(response, 'name="outcome"')
        response = self.post("location", self.part, {"outcome": f"design:{self.template.pk}@57x32", "copies": 1},
                             json=False)
        self.assertRedirects(response, self.part.get_absolute_url(), fetch_redirect_response=False)
        printed = self.zebra_output.printed[0][1]
        self.assertTrue(printed.startswith(b"^XA^PW456^LL256") and b"^GFA" in printed)

    def test_preview(self):
        url = reverse("print_preview", args=["item", self.item.pk])
        response = self.client.get(url, {"medium": self.tape.pk, "layout": f"design:{generated('item', 'tape12').pk}",
                                         "location": self.part.pk})
        self.assertEqual(response["Content-Type"], "image/png")
        image = Image.open(BytesIO(response.content))
        self.assertEqual(image.height, drivers.ptouch_print_pins("E550W", 12))
        self.assertFalse(LabelId.objects.exists())  # previews hand out no IDs
        self.assertEqual(self.client.get(url, {"medium": self.tape.pk, "layout": "nope"}).status_code, 404)

    def test_template_preview_as_the_printer_prints_it(self):
        url = reverse("print_preview", args=["location", self.part.pk])
        response = self.client.get(url, {"medium": self.labels.pk, "layout": f"design:{self.template.pk}"})
        self.assertEqual(Image.open(BytesIO(response.content)).size, (456, 256))

    def test_permission(self):
        self.client.force_login(get_user_model().objects.create_user("reader"))
        self.assertEqual(self.client.get(reverse("print_labels", args=["location", self.part.pk])).status_code, 403)
        response = self.client.get(self.part.get_absolute_url())
        self.assertContains(response, 'aria-label="Print labels"')  # disabled, with the reason
        self.assertNotContains(response, 'id="label-print-modal-location"')
        self.client.logout()
        self.assertNotContains(self.client.get(self.part.get_absolute_url()), "Print labels")

    def test_without_printers_the_button_says_why(self):
        PrintJob.objects.all().delete()
        self.labels.label_templates.clear()
        type(self.zebra).objects.update(is_active=False)
        response = self.client.get(self.part.get_absolute_url())
        self.assertContains(response, "No printer is set up for these labels yet.")
        self.assertNotContains(response, 'id="label-print-modal-location"')

    def test_item_page_with_location_from_the_label(self):
        response = self.client.get(self.item.get_absolute_url() + f"?loc={self.other_part.pk}")
        self.assertContains(response, "Take out at R303.b")
        self.assertContains(response, 'class="item-location-current" aria-current="location"')
        content = response.content.decode()
        self.assertLess(content.index("Take out at R303.b"), content.index("Take out at R303.a"))
        self.assertContains(response, 'data-direction="decrease"', count=2)
        # One location: just "Take out".
        ItemLocation.objects.filter(location=self.other_part).delete()
        self.assertContains(self.client.get(self.item.get_absolute_url()), "Take out</span>")


@override_settings(**SETTINGS)
class OpenAfterCreatingTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()

    def test_new_locations_open_the_dialog_for_whoever_may_print(self):
        request = RequestFactory().get("/")
        request.user = create_user("printer", "label_printing.print_label")
        self.assertEqual(with_print_dialog(request, self.part), self.part.get_absolute_url() + "?print=1")
        request.user = create_user("reader")
        self.assertEqual(with_print_dialog(request, self.part), self.part.get_absolute_url())


@override_settings(**SETTINGS)
class OutdatedLabelsTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, *_ = create_printers()
        cls.admin = get_user_model().objects.create_superuser("admin")

    def print_job(self, subject_type, subjects, layout):
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=layout, subject_type=subject_type,
                              subjects=subjects)
        PrintJob.objects.filter(pk=job.pk).update(status="done")
        return PrintJob.objects.get(pk=job.pk)

    def test_changed_codes_names_and_prices(self):
        location_job = self.print_job("location", [self.part], f"design:{generated('location', '57x32').pk}")
        item_job = self.print_job("item", [label_urls.ItemAt(self.item, self.part)],
                                  f"design:{generated('item', '57x32').pk}")
        self.assertEqual((services.outdated_reasons(location_job), services.outdated_reasons(item_job)), ([], []))
        self.shelf.short_name = "R304"
        self.shelf.save()
        Item.objects.filter(pk=self.item.pk).update(sale_price=Decimal("0.20"))
        self.assertEqual(services.outdated_reasons(location_job), ["R303.a is now R304.a"])
        self.assertEqual(services.outdated_reasons(item_job), ["Schrauben M4: price now 0.20 € / Stk"])

        self.client.force_login(self.admin)
        changelist = reverse("admin:label_printing_printjob_changelist")
        response = self.client.get(changelist, {"outdated": "1"})
        self.assertContains(response, "R303.a is now R304.a")
        with patch("label_printing.tasks.process_job.delay"):
            response = self.client.post(changelist, {"action": "reprint", "_selected_action": [location_job.pk, item_job.pk]},
                                        follow=True)
        self.assertContains(response, "printed again as job")
        newest = PrintJob.objects.order_by("-pk")[:2]
        self.assertEqual({job.label_code for job in newest}, {"R304.a", item_job.label_code})


@override_settings(**SETTINGS)
class QualityChoiceTests(InventoryData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.on_tape = f"design:{generated('location', 'tape12').pk}"
        cls.on_labels = f"design:{generated('location', '57x32').pk}"

    def test_high_quality_location_label_on_tape(self):
        job = services.submit(printer=self.brother, medium=self.tape, layout_key=self.on_tape, subject_type="location",
                              subjects=[self.part], quality="high")
        standard = services.submit(printer=self.brother, medium=self.tape, layout_key=self.on_tape,
                                   subject_type="location", subjects=[self.part])
        self.assertEqual((job.quality, standard.quality), ("high", "standard"))
        high_page, = simulator.decode_brother(bytes(job.payload))
        standard_page, = simulator.decode_brother(bytes(standard.payload))
        self.assertEqual(high_page.height, standard_page.height)
        # Twice the dots along the tape; QR modules snap to whole dots at either resolution
        self.assertAlmostEqual(high_page.width, 2 * standard_page.width, delta=standard_page.width * 0.1)

    def test_the_template_sets_the_quality(self):
        LocationLabelTemplate.objects.filter(pk=generated("location", "57x32").pk).update(quality="high")
        job = services.submit(printer=self.zebra, medium=self.labels, layout_key=self.on_labels, subject_type="location",
                              subjects=[self.part])
        self.assertEqual(job.quality, "high")
        self.assertIn("^PR2", bytes(job.payload).decode())
        with self.assertRaises(services.PrintError):
            services.submit(printer=self.zebra, medium=self.labels, layout_key=self.on_labels, subject_type="location",
                            subjects=[self.part], quality="best")
