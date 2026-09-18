from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BarcodeType, Item, ItemBarcode, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class InventoryPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="editor")
        cls.group = Group.objects.create(name="Inventory editors")
        cls.user.groups.add(cls.group)
        kind = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.root = Location.objects.create(name="Root", short_name="ROOT", type=kind)
        cls.destination = Location.objects.create(name="Destination", short_name="DEST", type=kind)
        cls.child = Location.objects.create(name="Child", short_name="CHILD", type=kind, parent_location=cls.root)
        cls.unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Original", measurement_unit=cls.unit)
        cls.stock = ItemLocation.objects.create(item=cls.item, location=cls.root, amount=3)

    def setUp(self):
        self.client.force_login(self.user)

    def grant(self, *codenames):
        self.group.permissions.set(Permission.objects.filter(content_type__app_label="inventory", codename__in=codenames))

    def item_data(self, **extra):
        return {"name": "Edited", "description": "", "measurement_unit": self.unit.pk, "barcode_data": "", **extra}

    def stock_data(self, *, extra=False):
        data = {
            "itemlocation_set-TOTAL_FORMS": "2" if extra else "1",
            "itemlocation_set-INITIAL_FORMS": "1",
            "itemlocation_set-0-id": self.stock.pk,
            "itemlocation_set-0-item": self.item.pk,
            "itemlocation_set-0-location": self.destination.pk,
            "itemlocation_set-0-amount": "5",
        }
        if extra:
            data.update({"itemlocation_set-1-location": self.destination.pk, "itemlocation_set-1-amount": "7"})
        return data

    def test_frontend_data_is_public(self):
        self.client.logout()
        for url in (
            reverse("index"), reverse("index_items"), reverse("index_locations"),
            self.root.get_absolute_url(), self.item.get_absolute_url(),
            reverse("print_inventory") + f"?locations={self.root.pk}",
            reverse("location-autocomplete"), reverse("parent_location_autocomplete"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get(self.root.get_absolute_url())
        self.assertNotContains(response, reverse("location_move", args=[self.root.pk]))
        self.assertNotContains(response, reverse("create_item"))
        self.assertNotContains(response, reverse("location_dissolve", args=[self.root.pk]))

    def test_frontend_requires_permissions_instead_of_inspecting_session(self):
        session = self.client.session
        session["is_zam_local"] = True
        session.save()
        for url in (
            reverse("create_item"), reverse("update_item", args=[self.item.pk]),
            reverse("annotate_item", args=[self.item.pk]), reverse("location_move", args=[self.child.pk]),
            reverse("locations_move_here", args=[self.root.pk]), reverse("location_dissolve", args=[self.root.pk]),
            reverse("update_location", args=[self.root.pk, self.root.unique_identifier]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.item_data()).status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Original")
        self.assertEqual(Item.objects.count(), 1)

    def test_group_permissions_control_buttons_and_move_requests(self):
        self.grant("change_location", "add_item", "add_itemlocation")
        response = self.client.get(self.root.get_absolute_url())
        self.assertContains(response, reverse("location_move", args=[self.root.pk]))
        self.assertContains(response, reverse("locations_move_here", args=[self.root.pk]))
        self.assertContains(response, reverse("create_item"))
        self.assertNotContains(response, reverse("location_dissolve", args=[self.root.pk]))
        response = self.client.post(reverse("location_move", args=[self.child.pk]), {"parent_location": self.destination.pk})
        self.assertEqual(response.status_code, 302)
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_location_id, self.destination.pk)

    def test_create_permission_does_not_allow_changing_existing_items(self):
        self.grant("add_item")
        self.assertEqual(self.client.get(reverse("create_item")).status_code, 200)
        response = self.client.post(reverse("create_item"), self.item_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Item.objects.count(), 2)
        self.assertEqual(self.client.post(reverse("update_item", args=[self.item.pk]), self.item_data()).status_code, 403)

    def test_metadata_edit_cannot_create_unpermitted_related_records(self):
        self.grant("change_item")
        url = reverse("update_item", args=[self.item.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'name="itemlocation_set-TOTAL_FORMS"')
        self.assertNotContains(response, 'id="add_image_button"')
        data = self.item_data(barcode_data="FORGED", **self.stock_data(extra=True))
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Edited")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.root.pk)
        self.assertEqual(ItemLocation.objects.count(), 1)
        self.assertFalse(ItemBarcode.objects.exists())

    def test_stock_change_permission_does_not_allow_forged_new_stock(self):
        self.grant("change_item", "change_itemlocation")
        url = reverse("update_item", args=[self.item.pk])
        response = self.client.get(url)
        self.assertContains(response, 'name="itemlocation_set-TOTAL_FORMS"')
        self.assertNotContains(response, 'name="itemimage_set-TOTAL_FORMS"')
        data = self.stock_data(extra=True)
        data["itemlocation_set-1-location"] = self.child.pk
        self.assertEqual(self.client.post(url, self.item_data(**data)).status_code, 403)
        self.stock.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.stock.amount, 3)
        self.assertEqual(self.item.name, "Original")
        self.assertEqual(ItemLocation.objects.count(), 1)

    def test_stock_add_permission_does_not_allow_changing_existing_stock(self):
        self.grant("change_item", "add_itemlocation")
        response = self.client.post(reverse("update_item", args=[self.item.pk]), self.item_data(**self.stock_data(extra=True)))
        self.assertEqual(response.status_code, 302)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.amount, 3)
        self.assertEqual(self.stock.location_id, self.root.pk)
        self.assertEqual(ItemLocation.objects.get(location=self.destination).amount, 7)

    def test_stock_change_and_annotation_work_with_permissions(self):
        self.grant("change_item", "change_itemlocation")
        self.assertEqual(self.client.post(reverse("update_item", args=[self.item.pk]), self.item_data(**self.stock_data())).status_code, 302)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.amount, 5)
        self.assertEqual(self.stock.location_id, self.destination.pk)
        response = self.client.post(reverse("annotate_item", args=[self.item.pk]), self.item_data(name="Annotated"))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Annotated")

    def test_photo_permissions_apply_to_existing_and_new_photos(self):
        image = ItemImage.objects.create(item=self.item, image="existing.gif", description="Original photo")
        url = reverse("update_item", args=[self.item.pk])
        data = self.item_data(**{
            "itemimage_set-TOTAL_FORMS": "2", "itemimage_set-INITIAL_FORMS": "1",
            "itemimage_set-0-id": image.pk, "itemimage_set-0-description": "Changed photo",
            "itemimage_set-1-description": "New photo",
        })
        gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
               b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            Path(directory, "existing.gif").write_bytes(gif)
            self.grant("change_item", "change_itemimage")
            data["itemimage_set-1-image"] = SimpleUploadedFile("test.gif", gif, content_type="image/gif")
            self.assertEqual(self.client.post(url, data).status_code, 403)
            image.refresh_from_db()
            self.assertEqual(image.description, "Original photo")
            self.assertEqual(ItemImage.objects.count(), 1)
            self.grant("change_item", "add_itemimage")
            data["itemimage_set-1-image"] = SimpleUploadedFile("test.gif", gif, content_type="image/gif")
            self.assertEqual(self.client.post(url, data).status_code, 302)
            image.refresh_from_db()
            self.assertEqual(image.description, "Original photo")
            self.assertEqual(ItemImage.objects.count(), 2)

    def test_barcode_types_and_barcode_deletions_require_separate_permissions(self):
        url = reverse("update_item", args=[self.item.pk])
        self.grant("change_item", "add_itembarcode")
        response = self.client.post(url, self.item_data(barcode_data="123 NEWTYPE"))
        self.assertContains(response, "You do not have permission to make these barcode changes.")
        self.assertFalse(BarcodeType.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Original")
        self.grant("change_item", "add_itembarcode", "add_barcodetype")
        self.assertEqual(self.client.post(url, self.item_data(barcode_data="123 NEWTYPE")).status_code, 302)
        self.assertEqual(ItemBarcode.objects.count(), 1)
        response = self.client.post(url, self.item_data(barcode_data=""))
        self.assertContains(response, "You do not have permission to make these barcode changes.")
        self.assertEqual(ItemBarcode.objects.count(), 1)
        self.grant("change_item", "delete_itembarcode")
        self.assertEqual(self.client.post(url, self.item_data()).status_code, 302)
        self.assertFalse(ItemBarcode.objects.exists())

    def test_dissolution_checks_each_operation_again_on_confirmation(self):
        self.grant("delete_location", "change_location", "change_itemlocation")
        url = reverse("location_dissolve", args=[self.root.pk])
        data = {f"item_{self.stock.pk}_destination": self.destination.pk, f"location_{self.child.pk}_destination": self.destination.pk}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        token = response.context["plan_token"]
        self.grant("delete_location", "change_location")
        self.assertEqual(self.client.post(url, {"stage": "confirm", "plan": token}).status_code, 403)
        self.stock.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.root.pk)
        self.assertEqual(self.child.parent_location_id, self.root.pk)
        self.assertTrue(Location.active.filter(pk=self.root.pk).exists())

    def test_dissolution_disables_unpermitted_moves_and_stock_deletion(self):
        self.grant("delete_location")
        url = reverse("location_dissolve", args=[self.root.pk])
        response = self.client.get(url)
        form = response.context["form"]
        self.assertTrue(form.fields["bulk_destination"].disabled)
        self.assertTrue(form.fields[f"item_{self.stock.pk}_delete"].disabled)
        self.assertTrue(form.fields[f"item_{self.stock.pk}_destination"].disabled)
        self.assertFalse(form.fields[f"location_{self.child.pk}_delete"].disabled)
        response = self.client.post(url, {f"item_{self.stock.pk}_delete": "on", f"location_{self.child.pk}_delete": "on"})
        self.assertNotIn("plan_token", response.context)
        self.assertTrue(ItemLocation.objects.filter(pk=self.stock.pk).exists())
        self.assertTrue(Location.active.filter(pk=self.child.pk).exists())

    def test_staff_cannot_bypass_create_or_delete_permissions(self):
        self.user.is_staff = True
        self.user.save()
        self.grant("change_item", "change_location")
        massadd = reverse("admin:inventory_location_massadd")
        self.assertEqual(self.client.get(massadd).status_code, 403)
        self.assertEqual(self.client.post(massadd, {}).status_code, 403)
        item_url = reverse("admin:inventory_item_change", args=[self.item.pk])
        response = self.client.get(item_url)
        self.assertNotContains(response, 'name="is_deleted"')
        response = self.client.post(item_url, self.item_data(is_deleted="on"))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_deleted)
        self.assertEqual(self.client.post(reverse("admin:inventory_item_delete", args=[self.item.pk]), {"post": "yes"}).status_code, 403)
        self.grant("change_item", "delete_item")
        self.assertContains(self.client.get(item_url), 'name="is_deleted"')
