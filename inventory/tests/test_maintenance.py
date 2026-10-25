from io import StringIO
import json
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.templatetags.static import static

from ..admin import LocationAdmin
from label_printing.models import LabelMedium, Printer, PrintJob
from ..models import Item, ItemImage, ItemLocation, Location, LocationLabelTemplate, LocationType, MeasurementUnit


@override_settings(LANGUAGE_CODE="en", LABEL_ID_BASE_URL="https://i.zam.haus/", CELERY_TASK_ALWAYS_EAGER=True)
class LabelPrintingTests(TestCase):
    """The admin's print actions queue jobs on the default printer (label_printing)."""

    @classmethod
    def setUpTestData(cls):
        template = LocationLabelTemplate.objects.create(name="Box", description="label 57 x 32\ntext {{ location.unique_identifier }}")
        kind = LocationType.objects.create(name="Room", unique=True, default_label_template=template)
        cls.locations = [Location.objects.create(name=f"Room {n}", short_name=f"R{n}", type=kind) for n in (1, 2)]
        cls.printer = Printer.objects.create(name="Zebra", slug="zebra", language="zpl", host="192.0.2.1",
                                             is_default=True)
        cls.medium = LabelMedium.objects.create(printer=cls.printer, name="57 × 32", width_mm=57, height_mm=32)
        cls.medium.label_templates.add(template)

    def run_action(self, action):
        request = RequestFactory().post("/")
        request.session = {}
        request._messages = FallbackStorage(request)
        request.user = get_user_model().objects.create_superuser(username=f"admin-{action.__name__}")
        with translation.override("en"), patch("label_printing.tasks.process_job.delay"):
            action(request, Location.objects.filter(pk__in=[location.pk for location in self.locations]))
        return [str(message) for message in get_messages(request)]

    def test_print_actions_queue_jobs_with_their_copies(self):
        model_admin = LocationAdmin(Location, admin.site)
        for copies, action in ((1, model_admin.send_to_printer_action), (2, model_admin.send_to_printer_twice_action)):
            with self.subTest(copies=copies):
                self.assertEqual(self.run_action(action), [f"Sent {2 * copies} labels to printer."])
                job = PrintJob.objects.latest("pk")
                self.assertEqual((job.copies, job.pages, job.printer), (copies, 2 * copies, self.printer))
                payload = bytes(job.payload).decode()
                self.assertEqual((payload.count("^XA"), payload.count(f"^PQ{copies}"), payload.count("^GFA")), (2, 2, 2))
                self.assertEqual(job.layout_key, f"design:{self.medium.label_templates.get().pk}")

    def test_without_default_printer(self):
        Printer.objects.update(is_default=False)
        self.assertEqual(self.run_action(LocationAdmin(Location, admin.site).send_to_printer_action), [
            "Failed sending label to printer: No default printer is set up (admin: Label printing → Printers).",
        ])


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

    def test_admin_mass_creation_keeps_children_and_computed_identifiers(self):
        room_type = LocationType.objects.create(
            name="Room", unique=True, auto_sequence="0123456789",
            auto_name_prefix="Room", auto_short_name_prefix="R",
        )
        box_type = LocationType.objects.create(
            name="Box", auto_sequence="0123456789",
            auto_name_prefix="Box", auto_short_name_prefix="B",
        )
        response = self.client.post(reverse("admin:inventory_location_massadd"), {
            "location_type": room_type.pk, "sequence_start": "1", "count": "2",
            "sub_type": box_type.pk, "sub_count": "2", "physical_description": "Storage",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(Location.objects.values_list("unique_identifier", flat=True)), {
            "R1", "R2", "R1.B0", "R1.B1", "R2.B0", "R2.B1",
        })
        self.assertEqual(Location.objects.filter(parent_location=None, physical_description="Storage").count(), 2)

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
            patch("inventory.management.commands.ocr.tqdm", side_effect=lambda iterable, **kwargs: iterable),
        ):
            pool = context.return_value.Pool.return_value.__enter__.return_value
            for text in ("First OCR pass", "Second OCR pass"):
                pool.imap.return_value = [(image.pk, text)]
                call_command("ocr", rerun=True, stdout=StringIO())
                image.refresh_from_db()
                self.assertEqual(image.ocr_text, text)

    def test_parent_autocomplete_excludes_self_and_descendants(self):
        kind = LocationType.objects.create(name="Room", unique=True)
        root = Location.objects.create(type=kind, name="Root", short_name="R")
        child = Location.objects.create(type=kind, name="Child", short_name="C", parent_location=root)
        Location.objects.create(type=kind, name="Leaf", short_name="L", parent_location=child)
        other = Location.objects.create(type=kind, name="Other", short_name="O")
        response = self.client.get(reverse("parent_location_autocomplete"), {"forward": json.dumps({"id": root.pk})})
        self.assertEqual({int(result["id"]) for result in response.json()["results"]}, {other.pk})
