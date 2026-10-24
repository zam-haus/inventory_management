from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import ImageChops

from inventory.label_ids import labels, services as label_ids
from inventory.label_ids.testing import make_id
from inventory.models import Item, LabelId, Location, LocationType, MeasurementUnit, UniqueItem
from .. import services, simulator
from ..layouts import REGISTRY, Canvas, layouts_for
from ..models import LabelMedium, PrintJob
from .helpers import SETTINGS, SimulatedPrinters, create_printers, create_user


@override_settings(**SETTINGS)
class LabelIdLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.lid = make_id("K7R4X")

    def test_designed_label_on_brother_tape_only(self):
        self.assertEqual([layout.key for layout in layouts_for("labelid", self.brother, self.tape)],
                         ["labelid", "labelid_plain"])
        self.assertEqual([layout.key for layout in layouts_for("labelid", self.zebra, self.labels)], ["labelid_plain"])
        wide = LabelMedium(printer=self.brother, name="36", ptouch_tape=36)  # the E550W has no 36 mm profile
        self.assertFalse(REGISTRY["labelid"].supports(self.brother, wide))

    def test_designed_label_is_the_downloadable_one(self):
        rendered = REGISTRY["labelid"].render(self.lid, Canvas.for_medium(self.tape), self.tape)
        expected = labels.image(self.lid.code, "E550W", 12)
        self.assertIsNone(ImageChops.difference(rendered.image.convert("L"), expected.convert("L")).getbbox())
        self.assertEqual(rendered.snapshot["qr"], f"HTTPS://I.ZAM.HAUS/{self.lid.code}")

    def test_plain_label_fills_the_medium(self):
        for medium in (self.labels, self.tape):
            canvas = Canvas.for_medium(medium)
            image = REGISTRY["labelid_plain"].render(self.lid, canvas, medium).image
            self.assertEqual(image.height, canvas.height)

    def test_designed_label_is_never_printed_in_high_resolution(self):
        job = services.submit(printer=self.brother, medium=self.tape, layout_key="labelid", subject_type="labelid",
                              subjects=[self.lid], quality="high")
        self.assertEqual(job.quality, "standard")
        page, = simulator.decode_brother(bytes(job.payload))
        self.assertEqual(page.width, labels.image(self.lid.code, "E550W", 12).width)


@override_settings(**SETTINGS)
class LabelIdPrintingTests(SimulatedPrinters, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers(cls.zebra_server.port, cls.brother_server.port)
        MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Stück", "short": "Stk"})
        room = Location.objects.create(name="Lager", short_name="WH", type=LocationType.objects.create(name="Room", unique=True))
        cls.unique_item = UniqueItem.objects.create(item=Item.objects.create(name="Bohrmaschine", kind="unique"),
                                                    location=room)
        cls.lid = label_ids.generate_and_claim(cls.unique_item, None)
        cls.user = create_user("printing", "label_printing.print_label", "inventory.view_labelid")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_printed_at_is_set_once_printed(self):
        with self.captureOnCommitCallbacks(execute=True):
            job = services.submit(printer=self.brother, medium=self.tape, layout_key="labelid",
                                  subject_type="labelid", subjects=[self.lid])
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        self.lid.refresh_from_db()
        self.assertIsNotNone(self.lid.printed_at)
        self.assertEqual(len(self.brother_output.printed), 1)

    def test_reprint(self):
        job = services.submit(printer=self.brother, medium=self.tape, layout_key="labelid", subject_type="labelid",
                              subjects=[self.lid])
        again = services.reprint(job)
        self.assertEqual((again.label_code, again.layout_key, again.pages), (self.lid.code, "labelid", 1))

    def test_failed_print_is_not_printed(self):
        self.brother_state.errors = ["cover_open"]
        with self.captureOnCommitCallbacks(execute=True):
            services.submit(printer=self.brother, medium=self.tape, layout_key="labelid", subject_type="labelid",
                            subjects=[self.lid])
        self.lid.refresh_from_db()
        self.assertIsNone(self.lid.printed_at)

    def test_unique_item_and_info_pages_offer_printing(self):
        for url in (self.unique_item.get_absolute_url(), reverse("label_id_info", args=[self.lid.code])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, reverse("print_labels", args=["labelid", self.lid.code]))
                self.assertContains(response, 'id="label-print-modal"')
                self.assertContains(response, f'<span class="label-print-subject">{self.lid.display}</span>')

    def test_dialog_prints_and_goes_back(self):
        url = reverse("print_labels", args=["labelid", self.lid.code])
        self.assertContains(self.client.get(url), self.lid.display)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"outcome": "labelid@tape12", "copies": 2})
        self.assertRedirects(response, reverse("label_id_info", args=[self.lid.code]), fetch_redirect_response=False)
        self.assertEqual(len(self.brother_output.printed), 2)
        preview = self.client.get(reverse("print_preview", args=["labelid", self.lid.code]),
                                  {"medium": self.tape.pk, "layout": "labelid"})
        self.assertEqual(preview["Content-Type"], "image/png")
        self.assertEqual(self.client.get(reverse("print_labels", args=["labelid", "NOPE00"])).status_code, 404)

    def test_admin_prints_selected_ids(self):
        reserved = [make_id(payload) for payload in ("12345", "5S8B2")]
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        changelist = reverse("admin:inventory_labelid_changelist")
        selected = {"action": "print_labels_action", "_selected_action": [lid.code for lid in reserved]}
        form = self.client.post(changelist, selected)
        self.assertContains(form, "P-touch Werkstatt: 12 mm")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(changelist, {**selected, "apply": "1", "medium": self.tape.pk, "copies": 1},
                                        follow=True)
        self.assertContains(response, "(+1): waiting")
        self.assertEqual(len(self.brother_output.printed), 2)
        self.assertFalse(LabelId.objects.filter(pk__in=[lid.pk for lid in reserved], printed_at=None).exists())

    def test_command_prints_a_batch_in_jobs_of_20(self):
        label_ids.generate_batch(25, batch="regal")
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("label_id_labels", "--batch", "regal", "--print", "ptouch", stdout=out)
        self.assertEqual(PrintJob.objects.filter(subject_type="labelid").count(), 2)
        self.assertEqual(len(self.brother_output.printed), 25)
        with self.assertRaisesMessage(CommandError, "no unprinted reserved IDs"):
            call_command("label_id_labels", "--batch", "regal", "--print", "ptouch", stdout=out)
        with self.assertRaisesMessage(CommandError, "no printer 'nope'"):
            call_command("label_id_labels", "--batch", "regal", "--print", "nope", "--all", stdout=out)
