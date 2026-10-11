from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from inventory.models import Item

from zamid import services
from zamid.models import ZamId

from .helpers import SETTINGS, InventoryFixture, make_id, zam_local_group


@override_settings(**SETTINGS)
class ClaimTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        User = get_user_model()
        cls.member = User.objects.create_user(username="member")
        cls.member.groups.add(zam_local_group())  # ZAM-local gets claim_zamid by migration
        cls.outsider = User.objects.create_user(username="outsider")
        cls.zid = make_id("K7Q4X")
        cls.url = reverse("zamid_claim", args=[cls.zid.code])

    def status(self):
        return ZamId.objects.get(pk=self.zid.pk).status

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/oidc/authenticate"))

    def test_permission_required(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"kind": "item", "item-item": self.item.pk}).status_code, 403)
        self.assertEqual(self.status(), ZamId.Status.RESERVED)

    def test_claim_existing_item(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.url), "K7Q-4XD")
        response = self.client.post(self.url, {"kind": "item", "item-item": self.item.pk})
        self.assertRedirects(response, self.item.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).item, self.item)
        # Claimed IDs are final: the claim page now just resolves.
        response = self.client.get(self.url)
        self.assertRedirects(response, "/id/K7Q4XD", fetch_redirect_response=False)
        self.client.post(self.url, {"kind": "item", "item-item": self.other_item.pk})
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).item, self.item)

    def test_claim_existing_location(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "location", "location-location": self.location.pk})
        self.assertRedirects(response, self.location.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).location, self.location)

    def test_claim_new_item(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "new_item", "new_item-name": "Laser cutter"})
        item = Item.objects.get(name="Laser cutter")
        self.assertRedirects(response, reverse("update_item", args=[item.pk]), fetch_redirect_response=False)
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).item, item)

    def test_target_with_active_id_is_refused(self):
        services.claim(make_id("12345").code, self.item, None)
        self.client.force_login(self.member)
        response = self.client.post(self.url, {"kind": "item", "item-item": self.item.pk})
        self.assertContains(response, "123-45V")
        self.assertEqual(self.status(), ZamId.Status.RESERVED)

    def test_failed_claim_does_not_create_item(self):
        services.retire(self.zid.code, None)
        self.client.force_login(self.member)
        self.client.post(self.url, {"kind": "new_item", "new_item-name": "Orphan"})
        self.assertFalse(Item.objects.filter(name="Orphan").exists())

    def test_search_jumps_to_id(self):
        services.claim(self.zid.code, self.item, None)
        for url in (reverse("index_items"), reverse("index_locations")):
            with self.subTest(url):
                response = self.client.get(url, {"q": "k7q-4xd"})
                self.assertRedirects(response, "/id/K7Q4XD", fetch_redirect_response=False)
                self.assertEqual(self.client.get(url, {"q": "Drill"}).status_code, 200)

    def test_item_autocomplete(self):
        url = reverse("zamid_item_autocomplete")
        self.assertNotContains(self.client.get(url, {"q": "Drill"}), "Drill")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(url, {"q": "Drill"}), "Drill")
        services.claim(self.zid.code, self.item, None)
        self.assertNotContains(self.client.get(url, {"q": "Drill"}), "Drill")

    def test_admin_add_with_zamid_claims(self):
        superuser = get_user_model().objects.create_superuser(username="admin")
        request = RequestFactory().post("/admin/inventory/item/add/?zamid=k7q-4xd")
        request.user, request.session = superuser, {}
        request._messages = FallbackStorage(request)
        item = Item(name="Via admin", measurement_unit=self.unit)
        admin.site._registry[Item].save_model(request, item, SimpleNamespace(changed_data=[]), False)
        self.assertEqual(ZamId.objects.get(pk=self.zid.pk).item, item)
