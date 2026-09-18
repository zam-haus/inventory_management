from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ItemForm
from .models import Item, ItemBarcode, ItemFile, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ], LANGUAGE_CODE="en",
)
class SoftDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kind = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.location = Location.objects.create(type=cls.kind, name="Storage", short_name="S")
        cls.other = Location.objects.create(type=cls.kind, name="Other", short_name="O")
        cls.unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Archived supply", measurement_unit=cls.unit)
        cls.stock = ItemLocation.objects.create(item=cls.item, location=cls.location, amount=4)
        cls.barcode = ItemBarcode.objects.create(item=cls.item, data="12345")
        cls.user = get_user_model().objects.create_user(username="admin", is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_item_first_delete_preserves_stock_and_barcode_second_removes_them(self):
        pk = self.item.pk
        self.item.delete()
        self.assertTrue(Item.objects.get(pk=pk).is_deleted)
        self.assertFalse(Item.active.filter(pk=pk).exists())
        self.assertTrue(ItemLocation.objects.filter(pk=self.stock.pk).exists())
        self.assertTrue(ItemBarcode.objects.filter(pk=self.barcode.pk).exists())
        self.item.delete()
        self.assertFalse(Item.objects.filter(pk=pk).exists())
        self.assertFalse(ItemLocation.objects.filter(pk=self.stock.pk).exists())
        self.assertFalse(ItemBarcode.objects.filter(pk=self.barcode.pk).exists())

    def test_mixed_bulk_delete_marks_active_items_and_removes_marked_items(self):
        archived = Item.objects.create(name="Already marked", measurement_unit=self.unit, is_deleted=True)
        archived_pk = archived.pk
        count, details = Item.objects.filter(pk__in=[self.item.pk, archived.pk]).delete()
        self.assertEqual(count, 2)
        self.assertEqual(details["inventory.Item"], 2)
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_deleted)
        self.assertFalse(Item.objects.filter(pk=archived_pk).exists())
        self.assertTrue(ItemLocation.objects.filter(pk=self.stock.pk).exists())

    def test_duplicate_join_rows_are_deleted_only_once(self):
        ItemLocation.objects.create(item=self.item, location=self.other, amount=8)
        queryset = Item.objects.filter(itemlocation__amount__gt=0)
        self.assertEqual(queryset.count(), 2)
        self.assertEqual(queryset.delete()[0], 1)
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_deleted)

    def test_location_second_deletion_requires_removing_archived_children(self):
        parent = Location.objects.create(type=self.kind, name="Parent", short_name="P")
        child = Location.objects.create(type=self.kind, name="Child", short_name="C", parent_location=parent)
        child.delete()
        parent.delete()
        with self.assertRaises(ValidationError):
            parent.delete()
        pks = [parent.pk, child.pk]
        self.assertEqual(Location.objects.filter(pk__in=pks).delete()[0], 2)
        self.assertFalse(Location.objects.filter(pk__in=pks).exists())

    def test_mixed_location_batch_does_not_delete_a_newly_marked_child_twice(self):
        # Simulate a manually inconsistent hierarchy to verify atomic rejection.
        parent = Location.objects.create(type=self.kind, name="Parent", short_name="P", is_deleted=True)
        child = Location.objects.create(type=self.kind, name="Child", short_name="C", parent_location=parent)
        with self.assertRaises(ValidationError):
            Location.objects.filter(pk__in=[parent.pk, child.pk]).delete()
        self.assertFalse(Location.objects.get(pk=child.pk).is_deleted)
        self.assertTrue(Location.objects.filter(pk=parent.pk).exists())

    def test_item_frontend_views_and_reports_hide_marked_items(self):
        pk = self.item.pk
        self.item.delete()
        for name in ("view_item", "update_item", "annotate_item"):
            url = reverse(name, args=[pk])
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in (reverse("index_items"), self.location.get_absolute_url()):
            self.assertNotContains(self.client.get(url), "Archived supply")
        response = self.client.get(reverse("print_inventory"), {"locations": self.location.pk})
        self.assertNotContains(response, "Archived supply")
        self.assertNotIn("is_deleted", ItemForm().fields)

    def test_archived_item_stock_can_still_be_evacuated_explicitly(self):
        self.item.delete()
        url = reverse("location_dissolve", args=[self.location.pk])
        page = self.client.get(url)
        self.assertContains(page, "Archived supply")
        self.assertContains(page, "(Deleted)")
        self.assertNotContains(page, f'href="{self.item.get_absolute_url()}"')
        review = self.client.post(url, {f"item_{self.stock.pk}_delete": True})
        self.client.post(url, {"stage": "confirm", "plan": review.context["plan_token"]})
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_deleted)
        self.assertTrue(Location.objects.get(pk=self.location.pk).is_deleted)

    def test_item_admin_filters_and_two_confirmation_stages(self):
        pk = self.item.pk
        url = reverse("admin:inventory_item_delete", args=[pk])
        review = self.client.get(url)
        self.assertContains(review, "Mark as deleted:")
        self.assertNotContains(review, "Permanently delete")
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertTrue(Item.objects.get(pk=pk).is_deleted)
        listing = reverse("admin:inventory_item_changelist")
        self.assertEqual(list(self.client.get(listing).context["cl"].result_list), [])
        self.assertContains(self.client.get(listing, {"is_deleted__exact": "1"}), "❌")
        self.assertContains(self.client.get(reverse("admin:inventory_item_change", args=[pk])), 'name="is_deleted"')
        review = self.client.get(url)
        self.assertContains(review, "Permanently delete")
        self.assertContains(review, "12345")
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertFalse(Item.objects.filter(pk=pk).exists())

    def test_location_admin_second_delete_removes_record(self):
        pk = self.other.pk
        self.other.delete()
        url = reverse("admin:inventory_location_delete", args=[pk])
        self.assertContains(self.client.get(url), "Permanently delete")
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertFalse(Location.objects.filter(pk=pk).exists())

    def test_attachment_cleanup_only_after_permanent_delete_commits(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            image = ItemImage.objects.create(item=self.item, image=SimpleUploadedFile("sample.png", b"image data"))
            attachment = ItemFile.objects.create(item=self.item, file=SimpleUploadedFile("manual.txt", b"manual"))
            image_path, file_path = Path(image.image.path), Path(attachment.file.path)
            pk = self.item.pk
            with self.captureOnCommitCallbacks(execute=True):
                self.item.delete()
            self.assertTrue(image_path.exists())
            self.assertTrue(file_path.exists())
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError), transaction.atomic():
                    Item.objects.get(pk=pk).delete()
                    raise RuntimeError("rollback")
            self.assertTrue(Item.objects.filter(pk=pk).exists())
            self.assertTrue(image_path.exists())
            self.assertTrue(file_path.exists())
            with self.captureOnCommitCallbacks(execute=True):
                Item.objects.get(pk=pk).delete()
            self.assertFalse(image_path.exists())
            self.assertFalse(file_path.exists())
