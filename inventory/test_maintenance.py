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
from django.utils import timezone

from .admin import LocationAdmin
from .models import Item, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit


class LabelPrintingTests(SimpleTestCase):
    def test_print_actions_preserve_copy_counts_and_failure_messages(self):
        model_admin = LocationAdmin(Location, admin.site)
        for copies, action in ((1, model_admin.send_to_printer_action), (2, model_admin.send_to_printer_twice_action)):
            with self.subTest(copies=copies):
                request = RequestFactory().post("/")
                request.session = {}
                request._messages = FallbackStorage(request)
                good, bad = Mock(), Mock()
                bad.send_to_printer.side_effect = RuntimeError("Printer unavailable")
                action(request, [good, bad])
                self.assertEqual(good.send_to_printer.call_count, copies)
                self.assertEqual(bad.send_to_printer.call_count, 1)
                self.assertEqual([str(message) for message in get_messages(request)], [
                    f"Sent {copies} label(s) to printer.",
                    "Failed sending 1 label(s) to printer: Printer unavailable",
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
            "sub_type": box_type.pk, "sub_count": "2", "description": "Storage",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(Location.objects.values_list("unique_identifier", flat=True)), {
            "R1", "R2", "R1.B0", "R1.B1", "R2.B0", "R2.B1",
        })
        self.assertEqual(Location.objects.filter(parent_location=None, description="Storage").count(), 2)

    def test_finishing_last_incomplete_item_keeps_annotation_page_available(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Last item", measurement_unit=unit)
        kind = LocationType.objects.create(name="Room", unique=True)
        location = Location.objects.create(type=kind, name="Storage", short_name="STORE")
        ItemLocation.objects.create(item=item, location=location, amount=1)
        ItemImage.objects.create(item=item, image="example.png")
        self.assertTrue(Item.filter_incomplete().exists())
        url = reverse("annotate_item", args=[item.pk])
        response = self.client.post(url, {
            "name": "Completed", "measurement_unit": unit.pk, "sale_price": "1.00", "save_next": "1",
        })
        self.assertRedirects(response, url)
        item.refresh_from_db()
        self.assertEqual(item.name, "Completed")

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
