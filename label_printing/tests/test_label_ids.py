from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from inventory.label_ids import services as label_ids
from inventory.label_ids.testing import make_id
from inventory.models import Item, LabelId, Location, LocationType, MeasurementUnit, UniqueItem
from .. import services
from ..design import parse
from ..layouts import Canvas, get_layout, layouts_for
from ..models import LabelMedium, PrintJob
from .helpers import SETTINGS, SimulatedPrinters, create_printers, create_user, generated, outcome_key


@override_settings(**SETTINGS)
class LabelIdLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zebra, cls.labels, cls.brother, cls.tape = create_printers()
        cls.lid = make_id("K7R4X")

    def keys(self, printer, medium):
        return [layout.key for layout in layouts_for("labelid", printer, medium)]

    def test_zamid_templates_for_every_label(self):
        for printer, medium, size in ((self.brother, self.tape, "tape12"), (self.zebra, self.labels, "57x32")):
            self.assertEqual(self.keys(printer, medium), [f"design:{generated(kind, size).pk}"
                                                          for kind in ("labelid", "labelid_plain")])
        wide = LabelMedium.objects.create(printer=self.brother, name="36", ptouch_tape=36)
        self.assertEqual(self.keys(self.brother, wide), [])  # the E550W has no 36 mm profile

    def test_zamid_on_every_tape_width_with_a_margin(self):
        for tape in (9, 12, 18, 24, 36):
            with self.subTest(tape=tape):
                design, problems = parse(generated("labelid", f"tape{tape}").description)
                top, _right, bottom, _left = design.margin
                self.assertEqual((problems, design.height, design.width), ([], tape, None))
                self.assertGreaterEqual(min(top, bottom), 1)

    def test_labels_fill_the_medium(self):
        for medium, size in ((self.labels, "57x32"), (self.tape, "tape12")):
            canvas = Canvas.for_medium(medium)
            for kind in ("labelid", "labelid_plain"):
                with self.subTest(medium=medium.name, kind=kind):
                    rendered = get_layout(f"design:{generated(kind, size).pk}").render(self.lid, canvas, medium)
                    self.assertEqual(rendered.image.height, canvas.height)
                    self.assertEqual((rendered.label_code, rendered.snapshot["qr"]),
                                     (self.lid.code, f"HTTPS://I.ZAM.HAUS/{self.lid.code}"))


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
        cls.zamid = f"design:{generated('labelid', 'tape12').pk}"

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_printed_at_is_set_once_printed(self):
        with self.captureOnCommitCallbacks(execute=True):
            job = services.submit(printer=self.brother, medium=self.tape, layout_key=self.zamid,
                                  subject_type="labelid", subjects=[self.lid])
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        self.lid.refresh_from_db()
        self.assertIsNotNone(self.lid.printed_at)
        self.assertEqual(len(self.brother_output.printed), 1)

    def test_reprint(self):
        job = services.submit(printer=self.brother, medium=self.tape, layout_key=self.zamid, subject_type="labelid",
                              subjects=[self.lid])
        again = services.reprint(job)
        self.assertEqual((again.label_code, again.layout_key, again.pages), (self.lid.code, self.zamid, 1))

    def test_failed_print_is_not_printed(self):
        self.brother_state.errors = ["cover_open"]
        with self.captureOnCommitCallbacks(execute=True):
            services.submit(printer=self.brother, medium=self.tape, layout_key=self.zamid, subject_type="labelid",
                            subjects=[self.lid])
        self.lid.refresh_from_db()
        self.assertIsNone(self.lid.printed_at)

    def test_unique_item_and_info_pages_offer_printing(self):
        for url in (self.unique_item.get_absolute_url(), reverse("label_id_info", args=[self.lid.code])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, reverse("print_labels", args=["labelid", self.lid.code]))
                self.assertContains(response, 'id="label-print-modal-labelid"')
                self.assertContains(response, f'<span class="label-print-subject">{self.lid.display}</span>')

    def test_dialog_prints_and_goes_back(self):
        url = reverse("print_labels", args=["labelid", self.lid.code])
        self.assertContains(self.client.get(url), self.lid.display)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"outcome": outcome_key("labelid", "tape12"), "copies": 2})
        self.assertRedirects(response, reverse("label_id_info", args=[self.lid.code]), fetch_redirect_response=False)
        self.assertEqual(len(self.brother_output.printed), 2)
        preview = self.client.get(reverse("print_preview", args=["labelid", self.lid.code]),
                                  {"medium": self.tape.pk, "layout": self.zamid})
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
