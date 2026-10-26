from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.templatetags.static import static

from label_printing.models import LabelMedium, Printer, PrintJob
from ..models import Item, ItemImage, Location, LocationLabelTemplate, LocationType, MeasurementUnit
from ..tasks import recognize_text
from .test_documents_and_photos import MediaMixin, png


@override_settings(LANGUAGE_CODE="en", LABEL_ID_BASE_URL="https://i.zam.haus/", CELERY_TASK_ALWAYS_EAGER=True)
class LabelPrintingTests(TestCase):
    """The admin prints labels as the print dialog does: the label (or each its preselected one) decides the
    printer (label_printing.admin_printing)."""

    @classmethod
    def setUpTestData(cls):
        cls.template = template = LocationLabelTemplate.objects.create(
            name="Box", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        kind = LocationType.objects.create(name="Room", unique=True)
        cls.locations = [Location.objects.create(name=f"Room {n}", short_name=f"R{n}", type=kind) for n in (1, 2)]
        cls.printer = Printer.objects.create(name="Zebra", slug="zebra", language="zpl", host="192.0.2.1")
        cls.medium = LabelMedium.objects.create(printer=cls.printer, name="57 × 32", width_mm=57, height_mm=32)
        cls.printer.loaded_medium = cls.medium
        cls.printer.save()
        LocationLabelTemplate.objects.exclude(pk=template.pk).update(is_active=False)
        cls.admin = get_user_model().objects.create_superuser(username="admin")

    def print_selected(self, **data):
        self.client.force_login(self.admin)
        with translation.override("en"), patch("label_printing.tasks.process_job.delay"):
            response = self.client.post(reverse("admin:inventory_location_changelist"), {
                "action": "print_labels_action", "_selected_action": [location.pk for location in self.locations],
                **data}, follow=True)
        return [str(message) for message in response.context["messages"]]

    def test_the_action_asks_for_the_label_and_its_copies(self):
        self.client.force_login(self.admin)
        page = self.client.post(reverse("admin:inventory_location_changelist"), {
            "action": "print_labels_action", "_selected_action": [location.pk for location in self.locations]})
        self.assertContains(page, "Each the one preselected for it")
        self.assertContains(page, "Box · 57 × 32 mm labels · Zebra")
        self.assertEqual(self.print_selected(apply="1", label="", copies="2"),
                         ["2 labels (Room 1 [R1] (+1)): on Zebra."])
        job = PrintJob.objects.get()
        self.assertEqual((job.copies, job.pages, job.printer, job.layout_key),
                         (2, 4, self.printer, f"design:{self.template.pk}"))
        payload = bytes(job.payload).decode()
        self.assertEqual((payload.count("^XA"), payload.count("^PQ2"), payload.count("^GFA")), (2, 2, 2))

    def test_a_chosen_label_and_labels_that_wait(self):
        label = f"design:{self.template.pk}@57x32"
        Printer.objects.update(loaded_medium=None)  # nothing loaded: the jobs wait for the labels
        self.assertEqual(self.print_selected(apply="1", label=label, copies="1"),
                         ["2 labels (Room 1 [R1] (+1)) wait for a printer with their labels."])
        self.assertEqual(PrintJob.objects.get().status, PrintJob.Status.WAITING)
        Printer.objects.update(is_active=False)  # no printer at all
        self.assertEqual(self.print_selected(apply="1", label="", copies="1"),
                         ["The labels could not be printed: No printer has labels of this size."])

    def test_the_change_page_prints_one_label(self):
        self.client.force_login(self.admin)
        url = reverse("admin:inventory_location_print-label", args=[self.locations[0].pk])
        self.assertContains(self.client.get(url), "Room 1")
        with patch("label_printing.tasks.process_job.delay"):
            response = self.client.post(url, {"apply": "1", "label": "", "copies": "1"})
        self.assertRedirects(response, reverse("admin:inventory_location_change", args=[self.locations[0].pk]),
                             fetch_redirect_response=False)
        self.assertEqual(PrintJob.objects.get().subject_label, "Room 1 [R1]")

    def test_printing_labels_is_for_who_may(self):
        """Printing labels is a privilege (label_printing.print_label, the local group), also in the admin."""
        from django.contrib.auth.models import Permission
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=[
            "view_location", "change_location", "add_location", "view_printer", "change_printer", "view_printjob"]))
        location = self.locations[0]
        self.client.force_login(staff)
        def actions(url):
            form = self.client.get(url).context["action_form"]  # none without any action
            return set(dict(form.fields["action"].choices)) if form else set()
        pages = {
            reverse("admin:inventory_location_changelist"): {"print_labels_action"},
            reverse("admin:label_printing_printer_changelist"): {"test_print", "calibration_print"},
            reverse("admin:label_printing_printjob_changelist"): {"reprint"},
        }
        for url, printing in pages.items():
            with self.subTest(url=url):
                self.assertFalse(printing & actions(url))
        change = reverse("admin:inventory_location_change", args=[location.pk])
        self.assertNotContains(self.client.get(change), "Print label")
        self.assertEqual(self.client.get(reverse("admin:inventory_location_print-label", args=[location.pk])).status_code,
                         403)
        self.assertFalse({"print", "label"} & set(self.client.get(reverse("admin:inventory_location_reserve"))
                                                  .context["form"].fields))
        # With the permission, all of it
        staff.user_permissions.add(Permission.objects.get(codename="print_label"))
        staff = get_user_model().objects.get(pk=staff.pk)
        self.client.force_login(staff)
        for url, printing in pages.items():
            with self.subTest(url=url, permitted=True):
                self.assertEqual(printing & actions(url), printing)
        self.assertContains(self.client.get(change), "Print label")
        self.assertIn("label", self.client.get(reverse("admin:inventory_location_reserve")).context["form"].fields)


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class MaintenanceRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="maintainer")
        self.client.force_login(self.user)

    def test_pages_link_the_favicon(self):
        svg = static("inventory/favicon/favicon.svg")  # with its version (?v=)
        self.assertTrue(svg.startswith("/static/inventory/favicon/favicon.svg?v="))
        icon = f'<link rel="icon" href="{svg}" type="image/svg+xml">'
        location = Location.objects.create(type=LocationType.objects.create(name="Room", unique=True), name="Root", short_name="R")
        for url in (reverse("index_locations"), reverse("index_items"), reverse("admin:index"),
                    reverse("print_inventory"), location.get_absolute_url()):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), icon, html=True)

    def test_navbar_shows_logo(self):
        logo = f'<img src="{static("inventory/favicon/favicon.svg")}" alt="ZAM inventory" width="40" height="40">'
        self.assertContains(self.client.get(reverse("index_items")), logo, html=True)

    @override_settings(DEBUG=True)
    def test_dev_system_uses_magenta_variant(self):
        response = self.client.get(reverse("index_items"))
        self.assertContains(response, 'src="/static/inventory/favicon/dev/favicon.svg?v=')
        self.assertContains(response, 'href="/static/inventory/favicon/dev/favicon.ico?v=')
        self.assertIn(b"#e94391", self.client.get("/favicon.svg").content)

    def test_admin_user_search_uses_existing_fields(self):
        get_user_model().objects.create_user(username="searchable", first_name="FindMe")
        response = self.client.get(reverse("admin:accounts_user_changelist"), {"q": "FindMe"})
        self.assertContains(response, "searchable")
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_ocr_timestamp_is_current_in_non_utc_timezone(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Photo", measurement_unit=unit)
        image = ItemImage.objects.create(item=item, image="example.png")
        before = timezone.now()
        with timezone.override("Europe/Berlin"):
            image.update_ocr_text("Read from photo")
        image.refresh_from_db()
        self.assertEqual(image.ocr_text, "Read from photo")
        self.assertLessEqual(before, image.ocr_timestamp)
        self.assertLessEqual(image.ocr_timestamp, timezone.now())

    def test_ocr_command_can_run_repeatedly_without_changing_global_process_settings(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Photo", measurement_unit=unit)
        image = ItemImage.objects.create(item=item, image="example.png")
        with (
            patch("inventory.management.commands.ocr.mp.get_context") as context,
            patch("inventory.management.commands.ocr.mp.set_start_method", side_effect=AssertionError("Global setting changed")),
            patch("inventory.management.commands.ocr.logger"),
            patch("inventory.management.commands.ocr.tqdm"),
        ):
            pool = context.return_value.Pool.return_value.__enter__.return_value
            for text in ("First OCR pass", "Second OCR pass"):
                pool.imap.return_value = [(image.pk, text)]
                call_command("ocr", rerun=True, stdout=StringIO())
                image.refresh_from_db()
                self.assertEqual(image.ocr_text, text)

    def test_ocr_command_saves_each_batch_before_loading_the_next(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Photo", measurement_unit=unit)
        images = [ItemImage.objects.create(item=item, image=f"example{i}.png") for i in range(5)]
        batches = []

        def imap(func, iterable):
            batches.append([image_id for image_id, _ in iterable])
            self.assertFalse(ItemImage.objects.filter(pk__in=batches[-1], ocr_timestamp__isnull=False).exists())
            return [(image_id, f"Text {image_id}") for image_id in batches[-1]]

        with (
            patch("inventory.management.commands.ocr.mp.get_context") as context,
            patch("inventory.management.commands.ocr.logger"),
            patch("inventory.management.commands.ocr.tqdm"),
        ):
            context.return_value.Pool.return_value.__enter__.return_value.imap.side_effect = imap
            call_command("ocr", rerun=True, batch_size=2, stdout=StringIO())
        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])
        for image in images:
            image.refresh_from_db()
            self.assertEqual(image.ocr_text, f"Text {image.pk}")

    def test_parent_autocomplete_excludes_self_and_descendants(self):
        kind = LocationType.objects.create(name="Room", unique=True)
        root = Location.objects.create(type=kind, name="Root", short_name="R")
        child = Location.objects.create(type=kind, name="Child", short_name="C", parent_location=root)
        Location.objects.create(type=kind, name="Leaf", short_name="L", parent_location=child)
        other = Location.objects.create(type=kind, name="Other", short_name="O")
        response = self.client.get(reverse("parent_location_autocomplete"), {"forward": json.dumps({"id": root.pk})})
        self.assertEqual({int(result["id"]) for result in response.json()["results"]}, {other.pk})


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class OcrOnUploadTests(MediaMixin, TestCase):
    """With a Celery worker, new and replaced photos get their text recognized in the background (queue ocr)."""

    @classmethod
    def setUpTestData(cls):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Photo", measurement_unit=unit)

    def test_new_and_replaced_photos_are_queued_once_committed(self):
        with patch("inventory.tasks.recognize_text.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                image = ItemImage.objects.create(item=self.item, image=png("red"))
                self.assertFalse(delay.called)
            self.assertEqual(len(callbacks), 1)
            delay.assert_called_once_with(image.pk)
            image.update_ocr_text("Read from photo")
            image.description = "Box"
            with self.captureOnCommitCallbacks(execute=True):
                image.save()
            self.assertEqual(delay.call_count, 1)
            image.image = png("blue")
            with self.captureOnCommitCallbacks(execute=True):
                image.save()
            self.assertEqual(delay.call_count, 2)
            self.assertIsNone(image.ocr_timestamp)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_without_a_worker_nothing_is_queued(self):
        with patch("inventory.tasks.recognize_text.delay") as delay, self.captureOnCommitCallbacks(execute=True):
            ItemImage.objects.create(item=self.item, image=png("red"))
        delay.assert_not_called()

    def test_task_saves_the_text(self):
        image = ItemImage.objects.create(item=self.item, image=png("red"))
        with patch("inventory.tasks.ocr_on_image_path", return_value="HSS 6mm") as ocr:
            recognize_text(image.pk)
            ocr.assert_called_once_with(image.image.path)
            image.refresh_from_db()
            self.assertEqual(image.ocr_text, "HSS 6mm")
            self.assertIsNotNone(image.ocr_timestamp)
            # Already recognized (manage.py ocr) or deleted meanwhile: nothing to do.
            recognize_text(image.pk)
            recognize_text(image.pk + 1)
            self.assertEqual(ocr.call_count, 1)

    def test_task_keeps_changes_made_meanwhile(self):
        image = ItemImage.objects.create(item=self.item, image=png("red"))

        def edited_while_recognizing(path):
            ItemImage.objects.filter(pk=image.pk).update(description="Box")
            return "Old text"

        with patch("inventory.tasks.ocr_on_image_path", side_effect=edited_while_recognizing):
            recognize_text(image.pk)
        image.refresh_from_db()
        self.assertEqual((image.description, image.ocr_text), ("Box", "Old text"))

        # Replaced meanwhile: the text belongs to the old file; the new file's own task recognizes it.
        image.image = png("green")
        image.save()

        def replaced_while_recognizing(path):
            ItemImage.objects.filter(pk=image.pk).update(image="items/other.png")
            return "Text of the replaced file"

        with patch("inventory.tasks.ocr_on_image_path", side_effect=replaced_while_recognizing):
            recognize_text(image.pk)
        image.refresh_from_db()
        self.assertIsNone(image.ocr_text)
