from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from ..forms import ItemLocationForm
from ..icons import icon
from ..models import Item, ItemBarcode, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit


def png(name="photo.png"):
    content = BytesIO()
    Image.new("RGB", (4, 4)).save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


def permissions(*codenames):
    return [Permission.objects.get(content_type__app_label="inventory", codename=codename) for codename in codenames]


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class QuickItemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # New items use the measurement unit with the field's default primary key.
        cls.unit = MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        kind = LocationType.objects.create(name="Shelf", unique=True)
        cls.location = Location.objects.create(type=kind, name="Workbench", short_name="WB")
        cls.other_location = Location.objects.create(type=kind, name="Cabinet", short_name="CAB")
        User = get_user_model()
        # Mirrors the local group: may create and change, but not delete.
        cls.creator = User.objects.create_user(username="creator")
        cls.creator.user_permissions.add(*permissions(
            "add_item", "change_item", "add_itemlocation", "change_itemlocation",
        ))
        cls.reader = User.objects.create_user(username="reader")
        cls.item_only = User.objects.create_user(username="item-only")
        cls.item_only.user_permissions.add(*permissions("add_item"))

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.client.force_login(self.creator)
        self.create_url = reverse("quick_item_create", args=[self.location.pk])

    def quick_item(self, name="Soldering iron", location=None):
        item = Item.objects.create(name=name)
        return ItemLocation.objects.create(item=item, location=location or self.location, amount=None)

    def post_json(self, url, data=None, client=None):
        return (client or self.client).post(url, data or {}, HTTP_ACCEPT="application/json")

    def test_creating_a_quick_item_stores_only_a_title_and_unknown_amount(self):
        response = self.post_json(self.create_url, {"name": "  Hot   glue gun "})
        self.assertEqual(response.status_code, 200)
        entry = ItemLocation.objects.select_related("item").get()
        self.assertEqual(entry.item.name, "Hot glue gun")
        self.assertIsNone(entry.amount)
        self.assertEqual(entry.location, self.location)
        self.assertTrue(entry.is_quick_item)
        self.assertEqual(response.json(), {"ok": True, "entry": {
            "id": entry.pk, "name": "Hot glue gun", "item_url": entry.item.get_absolute_url(),
            "update_url": reverse("quick_item_update", args=[entry.pk]),
            "delete_url": reverse("quick_item_delete", args=[entry.pk]),
            "photo_url": reverse("quick_item_set_photo", args=[entry.pk]), "photo": None,
        }})

    def test_creating_without_javascript_returns_to_the_quick_item_list(self):
        response = self.client.post(self.create_url, {"name": "Multimeter"})
        self.assertRedirects(response, f"{self.location.get_absolute_url()}#location-items")
        self.assertTrue(Item.active.filter(name="Multimeter").exists())

    def test_blank_or_overlong_names_create_nothing(self):
        for name in ("", "   ", "x" * 513):
            with self.subTest(length=len(name)):
                response = self.post_json(self.create_url, {"name": name})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertTrue(response.json()["error"])
        self.assertFalse(Item.objects.exists())

    def test_renaming_updates_the_item_title(self):
        entry = self.quick_item()
        response = self.post_json(reverse("quick_item_update", args=[entry.pk]), {"name": " Soldering  station "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entry"]["name"], "Soldering station")
        entry.item.refresh_from_db()
        self.assertEqual(entry.item.name, "Soldering station")

    def test_emptying_a_line_hard_deletes_the_quick_item(self):
        entry = self.quick_item()
        response = self.post_json(reverse("quick_item_update", args=[entry.pk]), {"name": "  "})
        self.assertEqual(response.json(), {"ok": True, "deleted": True})
        self.assertFalse(Item.objects.filter(pk=entry.item_id).exists())
        self.assertFalse(ItemLocation.objects.filter(pk=entry.pk).exists())

    def test_delete_is_permanent_and_needs_no_delete_permission(self):
        entry = self.quick_item()
        self.assertFalse(self.creator.has_perm("inventory.delete_item"))
        response = self.post_json(reverse("quick_item_delete", args=[entry.pk]))
        self.assertEqual(response.json(), {"ok": True, "deleted": True})
        self.assertFalse(Item.objects.filter(pk=entry.item_id).exists())

    def test_deleting_without_javascript_reports_the_deletion(self):
        entry = self.quick_item()
        response = self.client.post(reverse("quick_item_delete", args=[entry.pk]))
        self.assertRedirects(response, f"{self.location.get_absolute_url()}#location-items")
        self.assertEqual([str(message) for message in get_messages(response.wsgi_request)], ["Quick-item “Soldering iron” deleted."])

    def test_beacon_deletion_answers_with_json_and_leaves_no_message(self):
        entry = self.quick_item()
        response = self.client.post(reverse("quick_item_delete", args=[entry.pk]), {"format": "json"})
        self.assertEqual(response.json(), {"ok": True, "deleted": True})
        self.assertEqual(list(get_messages(response.wsgi_request)), [])

    def test_items_with_an_amount_are_no_longer_quick_items(self):
        entry = self.quick_item()
        ItemLocation.objects.filter(pk=entry.pk).update(amount=Decimal("3"))
        for url, data in (
            (reverse("quick_item_update", args=[entry.pk]), {"name": "Renamed"}),
            (reverse("quick_item_update", args=[entry.pk]), {"name": ""}),
            (reverse("quick_item_delete", args=[entry.pk]), {}),
        ):
            with self.subTest(url=url, data=data):
                response = self.post_json(url, data)
                self.assertEqual(response.status_code, 409)
                self.assertFalse(response.json()["ok"])
        entry.item.refresh_from_db()
        self.assertEqual(entry.item.name, "Soldering iron")
        self.assertFalse(entry.item.is_deleted)

    def test_quick_items_with_other_details_cannot_be_hard_deleted(self):
        details = {
            "second photo": lambda item: [ItemImage.objects.create(item=item, image=png()) for _ in range(2)],
            "barcode": lambda item: ItemBarcode.objects.create(item=item, data="4006381333931"),
            "second location": lambda item: ItemLocation.objects.create(item=item, location=self.other_location, amount=None),
        }
        for detail, add in details.items():
            with self.subTest(detail=detail):
                entry = self.quick_item(name=f"With {detail}")
                add(entry.item)
                response = self.post_json(reverse("quick_item_delete", args=[entry.pk]))
                self.assertEqual(response.status_code, 409)
                self.assertTrue(Item.active.filter(pk=entry.item_id).exists())

    def test_permissions_are_required_for_every_operation(self):
        entry = self.quick_item()
        urls = [
            (self.create_url, {"name": "Forbidden"}),
            (reverse("quick_item_update", args=[entry.pk]), {"name": "Forbidden"}),
            (reverse("quick_item_delete", args=[entry.pk]), {}),
        ]
        for user in (None, self.reader, self.item_only):
            client = Client()
            if user:
                client.force_login(user)
            for url, data in urls:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.post_json(url, data, client=client).status_code, 403)
        entry.item.refresh_from_db()
        self.assertEqual(entry.item.name, "Soldering iron")
        self.assertEqual(Item.objects.count(), 1)

    def test_csrf_and_post_are_required(self):
        self.assertEqual(self.client.get(self.create_url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.creator)
        self.assertEqual(client.post(self.create_url, {"name": "No token"}).status_code, 403)
        self.assertFalse(Item.objects.exists())

    def test_deleted_locations_and_items_are_not_found(self):
        entry = self.quick_item()
        Location.objects.filter(pk=self.location.pk).update(is_deleted=True)
        self.assertEqual(self.post_json(self.create_url, {"name": "Archived"}).status_code, 404)
        self.assertEqual(self.post_json(reverse("quick_item_delete", args=[entry.pk])).status_code, 404)
        Location.objects.filter(pk=self.location.pk).update(is_deleted=False)
        Item.objects.filter(pk=entry.item_id).update(is_deleted=True)
        self.assertEqual(self.post_json(reverse("quick_item_update", args=[entry.pk]), {"name": "X"}).status_code, 404)

    def test_location_page_lists_quick_items_first_in_the_items_panel_and_counts_them(self):
        quick = self.quick_item()
        regular = Item.objects.create(name="Screwdriver set")
        ItemLocation.objects.create(item=regular, location=self.location, amount=2)
        response = self.client.get(self.location.get_absolute_url())
        content = response.content.decode()
        self.assertEqual(response.context["quick_entries"], [quick])
        self.assertEqual([entry.item for entry in response.context["entries"]], [regular])
        self.assertLess(content.index('id="location-items-heading"'), content.index('id="location-quick-items"'))
        self.assertLess(content.index('id="location-quick-items"'), content.index("Screwdriver set"))
        self.assertNotContains(response, 'id="location-quick-items-heading"')
        self.assertNotContains(response, 'href="#location-quick-items"')
        self.assertEqual(content.count('data-items-count>2<'), 2)  # panel heading and overview at the top
        self.assertContains(response, 'value="Soldering iron"')
        self.assertContains(response, f'action="{self.create_url}"')
        self.assertContains(response, quick.item.get_absolute_url())
        self.assertContains(response, "location_quick_items.js")

    def test_readers_see_quick_items_as_links_and_nothing_when_empty(self):
        self.client.force_login(self.reader)
        response = self.client.get(self.location.get_absolute_url())
        self.assertNotContains(response, 'id="location-quick-items"')
        self.assertNotContains(response, "location_quick_items.js")
        entry = self.quick_item()
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, 'id="location-quick-items"')
        self.assertContains(response, f'<a href="{entry.item.get_absolute_url()}">Soldering iron</a>', html=True)
        self.assertNotContains(response, self.create_url)
        self.assertNotContains(response, 'name="name"')

    def test_quick_items_are_found_by_the_item_search_and_shown_with_unknown_amount(self):
        entry = self.quick_item(name="Crimping tool")
        self.assertEqual(entry.amount_text, "amount unknown")
        self.assertIsNone(entry.sale_value)
        response = self.client.get(reverse("index_items"), {"q": "crimp"})
        self.assertEqual(list(response.context["object_list"]), [entry.item])
        self.assertContains(response, "amount unknown")
        self.assertContains(self.client.get(entry.item.get_absolute_url()), "amount unknown")

    def test_printable_inventory_includes_quick_items(self):
        self.quick_item(name="Crimping tool")
        self.creator.user_permissions.add(*permissions("print_inventory"))
        response = self.client.get(reverse("print_inventory"), {"locations": [self.location.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crimping tool")
        self.assertContains(response, "amount unknown")

    def test_location_list_print_button_carries_the_search(self):
        response = self.client.get(reverse("index_locations"), {"q": "Shelf A&B"})
        self.assertNotContains(response, reverse("print_inventory"))
        self.assertContains(response, 'aria-label="Print inventory of the locations found"')  # visible, but disabled
        self.creator.user_permissions.add(*permissions("print_inventory"))
        response = self.client.get(reverse("index_locations"), {"q": " Shelf A&B "})
        self.assertContains(response, reverse("print_inventory") + "?q=Shelf%20A%26B")
        # The printer icon with a short text; the tooltip names what is printed.
        self.assertContains(response, icon("printer") + ' <span class="action-label">Print</span></a>', html=False)

    def test_location_list_offers_printing_only_for_a_search(self):
        self.creator.user_permissions.add(*permissions("print_inventory"))
        for params in ({}, {"q": ""}, {"q": "   "}):
            with self.subTest(params=params):
                response = self.client.get(reverse("index_locations"), params)
                self.assertNotContains(response, reverse("print_inventory"))
                self.assertNotContains(response, "bi-printer")

    def test_entering_an_amount_turns_a_quick_item_into_a_regular_item(self):
        entry = self.quick_item()
        form = ItemLocationForm(data={"location": self.location.pk, "amount": ""}, instance=entry)
        self.assertTrue(form.is_valid(), form.errors)
        form = ItemLocationForm(data={"location": self.location.pk, "amount": "5"}, instance=entry)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        entry.refresh_from_db()
        self.assertFalse(entry.is_quick_item)
        # Regular items and new storage entries still need an amount.
        for instance in (entry, None):
            with self.subTest(instance=instance):
                form = ItemLocationForm(data={"location": self.other_location.pk, "amount": ""}, instance=instance)
                self.assertIn("amount", form.errors)

    # ------------------------------------------------------------ single photo
    def grant_photos(self):
        self.creator.user_permissions.add(*permissions("add_itemimage"))
        self.creator = type(self.creator).objects.get(pk=self.creator.pk)  # drop the permission cache
        self.client.force_login(self.creator)

    def test_a_quick_item_gets_a_single_photo_and_a_new_one_replaces_it(self):
        self.grant_photos()
        entry = self.quick_item()
        url = reverse("quick_item_set_photo", args=[entry.pk])
        response = self.client.post(url, {"image": png("first.png")}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        photo = response.json()["entry"]["photo"]
        first = ItemImage.objects.get(item=entry.item)
        self.assertEqual(photo["url"], first.image.url)
        self.assertTrue(photo["thumbnail"])
        self.client.post(url, {"image": png("second.png")}, HTTP_ACCEPT="application/json")
        self.assertEqual(ItemImage.objects.filter(item=entry.item).count(), 1)
        self.assertNotEqual(ItemImage.objects.get(item=entry.item).pk, first.pk)
        self.assertTrue(entry.is_quick_item)

    def test_photo_without_javascript_returns_to_the_items_panel(self):
        self.grant_photos()
        entry = self.quick_item()
        response = self.client.post(reverse("quick_item_set_photo", args=[entry.pk]), {"image": png()})
        self.assertRedirects(response, f"{self.location.get_absolute_url()}#location-items")
        self.assertTrue(ItemImage.objects.filter(item=entry.item).exists())

    def test_photo_needs_the_image_permission_and_a_quick_item_with_at_most_one_photo(self):
        entry = self.quick_item()
        url = reverse("quick_item_set_photo", args=[entry.pk])
        self.assertEqual(self.client.post(url, {"image": png()}, HTTP_ACCEPT="application/json").status_code, 403)
        self.grant_photos()
        self.assertEqual(self.client.post(url, {}, HTTP_ACCEPT="application/json").status_code, 400)
        not_an_image = SimpleUploadedFile("photo.png", b"no image", content_type="image/png")
        self.assertEqual(self.client.post(url, {"image": not_an_image}, HTTP_ACCEPT="application/json").status_code, 400)
        ItemImage.objects.create(item=entry.item, image=png())
        ItemImage.objects.create(item=entry.item, image=png())
        self.assertEqual(self.client.post(url, {"image": png()}, HTTP_ACCEPT="application/json").status_code, 409)
        regular = self.quick_item("Regular")
        ItemLocation.objects.filter(pk=regular.pk).update(amount=3)
        response = self.client.post(reverse("quick_item_set_photo", args=[regular.pk]), {"image": png()}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ItemImage.objects.count(), 2)

    def test_deleting_a_quick_item_takes_its_single_photo_along(self):
        entry = self.quick_item()
        ItemImage.objects.create(item=entry.item, image=png())
        self.assertEqual(self.post_json(reverse("quick_item_delete", args=[entry.pk])).status_code, 200)
        self.assertFalse(Item.objects.filter(pk=entry.item_id).exists())
        self.assertFalse(ItemImage.objects.exists())

    def test_location_page_shows_the_photo_and_offers_the_upload_only_with_permission(self):
        entry = self.quick_item()
        ItemImage.objects.create(item=entry.item, image=png())
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, 'class="location-quick-photo"')
        self.assertNotContains(response, reverse("quick_item_set_photo", args=[entry.pk]))
        self.assertContains(response, 'aria-label="Add a photo"')  # visible, but disabled
        self.grant_photos()
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, f'action="{reverse("quick_item_set_photo", args=[entry.pk])}"')
        self.assertContains(response, 'accept="image/*"')
        self.client.force_login(self.reader)
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, 'class="location-quick-photo"')
        self.assertNotContains(response, 'name="image"')
