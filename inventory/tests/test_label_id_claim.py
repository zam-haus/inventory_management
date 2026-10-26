from types import SimpleNamespace

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.shortcuts import resolve_url
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from inventory.models import Item, Location, UniqueItem

from inventory.label_ids import services
from inventory.models import LabelId

from ..label_ids.testing import SETTINGS, InventoryFixture, make_id, local_group


@override_settings(**SETTINGS)
class ClaimTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        User = get_user_model()
        cls.member = User.objects.create_user(username="member")
        cls.member.groups.add(local_group())  # the local group gets claim_labelid by migration
        cls.outsider = User.objects.create_user(username="outsider")
        cls.lid = make_id("K7R4X")
        cls.url = reverse("label_id_claim", args=[cls.lid.code])

    def status(self):
        return LabelId.objects.get(pk=self.lid.pk).status

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(resolve_url(settings.LOGIN_URL)))

    def test_permission_required(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"kind": "item", "item-item": self.item.pk}).status_code, 403)
        self.assertEqual(self.status(), LabelId.Status.RESERVED)

    def test_page_loads_the_scripts_of_all_its_forms_once_after_jquery(self):
        # The new item's category search (Select2) needs jQuery, like the autocompletes of the other forms.
        self.client.force_login(self.member)
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count("select2/select2.full.js"), 1)
        self.assertIn("inventory/category_select.js", html)
        self.assertLess(html.index("static_jquery/js/jquery.min.js"), html.index("select2/select2.full.js"))

    def test_claim_existing_item(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.url), "K7R-4XD")
        response = self.client.post(self.url, {"kind": "item", "item-item": self.item.pk})
        self.assertRedirects(response, self.item.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).item, self.item)
        # Claimed IDs are final: the claim page now just resolves.
        response = self.client.get(self.url)
        self.assertRedirects(response, "/id/K7R4XD", fetch_redirect_response=False)
        self.client.post(self.url, {"kind": "item", "item-item": self.other_item.pk})
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).item, self.item)

    def test_claim_existing_location(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "location", "location-location": self.location.pk})
        self.assertRedirects(response, self.location.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).location, self.location)

    def test_claim_new_item(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "new_item", "new_item-name": "Laser cutter"})
        item = Item.objects.get(name="Laser cutter")
        self.assertRedirects(response, reverse("update_item", args=[item.pk]), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).item, item)

    def test_target_with_active_id_is_refused(self):
        services.claim(make_id("12345").code, self.item, None)
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "item", "item-item": self.item.pk})
        self.assertContains(response, "123-45V")
        self.assertEqual(self.status(), LabelId.Status.RESERVED)

    def test_failed_claim_does_not_create_item(self):
        services.retire(self.lid.code, None)
        self.client.force_login(self.member)
        self.client.post(self.url, {"kind": "new_item", "new_item-name": "Orphan"})
        self.assertFalse(Item.objects.filter(name="Orphan").exists())

    def test_search_jumps_to_id(self):
        services.claim(self.lid.code, self.item, None)
        response = self.client.get(reverse("index"), {"q": "k7r-4xd"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/id/K7R4XD?via="))
        self.assertEqual(self.client.get(reverse("index"), {"q": "Drill"}).status_code, 200)
        # The old lists' searches lead there.
        for url in (reverse("index_items"), reverse("index_locations")):
            with self.subTest(url):
                chain = self.client.get(url, {"q": "k7r-4xd"}, follow=True).redirect_chain
                self.assertTrue(chain[1][0].startswith("/id/K7R4XD?via="))

    def test_item_autocomplete(self):
        url = reverse("label_id_item_autocomplete")
        self.assertNotContains(self.client.get(url, {"q": "Drill"}), "Drill")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(url, {"q": "Drill"}), "Drill")
        services.claim(self.lid.code, self.item, None)
        self.assertNotContains(self.client.get(url, {"q": "Drill"}), "Drill")

    def test_admin_add_with_label_id_claims(self):
        superuser = get_user_model().objects.create_superuser(username="admin")
        request = RequestFactory().post("/admin/inventory/item/add/?label_id=k7r-4xd")
        request.user, request.session = superuser, {}
        request._messages = FallbackStorage(request)
        item = Item(name="Via admin", measurement_unit=self.unit)
        admin.site._registry[Item].save_model(request, item, SimpleNamespace(changed_data=[]), False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).item, item)


@override_settings(**SETTINGS)
class UniqueItemClaimTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.groups.add(local_group())  # add_uniqueitem by inventory/migrations/0024
        cls.extinguisher = Item.objects.create(name="Fire extinguisher", kind=Item.Kind.UNIQUE, measurement_unit=cls.unit)
        cls.lid = make_id("K7R4X")
        cls.url = reverse("label_id_claim", args=[cls.lid.code])

    def test_new_unique_item_from_a_scanned_label(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.url), "Create unique item with this ID")
        response = self.client.post(self.url, {"kind": "new_unique_item", "new_unique_item-item": self.extinguisher.pk,
                                               "new_unique_item-location": self.location.pk})
        unique_item = UniqueItem.objects.get()
        self.assertRedirects(response, reverse("update_unique_item", args=[unique_item.pk]), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).unique_item, unique_item)
        self.assertEqual(unique_item.change_log.get(action="created").actor, self.member)
        self.assertEqual(unique_item.change_log.get(action="label_id").details["event"], "assigned")
        # The resolver leads to the unique item from now on.
        response = self.client.get(reverse("label_id_resolve", args=[self.lid.code]))
        self.assertRedirects(response, unique_item.get_absolute_url(), fetch_redirect_response=False)

    def test_new_unique_item_with_a_new_item(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "new_unique_item", "new_unique_item-item": "new:Laser cutter",
                                               "new_unique_item-location": self.location.pk})
        cutter = Item.objects.get(name="Laser cutter")
        unique_item = cutter.unique_items.get()
        self.assertRedirects(response, reverse("update_unique_item", args=[unique_item.pk]), fetch_redirect_response=False)
        self.assertEqual((cutter.kind, LabelId.objects.get(pk=self.lid.pk).unique_item), (Item.Kind.UNIQUE, unique_item))

    def test_stock_items_are_not_unique_item_types(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "new_unique_item", "new_unique_item-item": self.item.pk,
                                               "new_unique_item-location": self.location.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UniqueItem.objects.exists())

    def test_replacement_label_only_for_unique_items_without_id(self):
        unique_item = UniqueItem.objects.create(item=self.extinguisher, location=self.location)
        old = services.claim(make_id("12345").code, unique_item, None)
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(self.url), "Replacement label")
        response = self.client.post(self.url, {"kind": "unique_item", "unique_item-unique_item": unique_item.pk})
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).status, LabelId.Status.RESERVED)
        services.retire(old.code, None, "label damaged")
        self.assertContains(self.client.get(self.url), "Replacement label")
        response = self.client.post(self.url, {"kind": "unique_item", "unique_item-unique_item": unique_item.pk})
        self.assertRedirects(response, unique_item.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).unique_item, unique_item)
