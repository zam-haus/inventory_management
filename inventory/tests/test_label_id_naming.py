from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.label_ids import services

from ..label_ids.testing import SETTINGS, InventoryFixture, make_id


@override_settings(**{**SETTINGS, "LABEL_ID_NAME": "ACMEid"})
class ConfigurableNameTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.lid = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.admin = get_user_model().objects.create_user(username="admin", is_staff=True, is_superuser=True)

    def test_resolver_pages_use_the_name(self):
        response = self.client.get("/", headers={"host": "id.zam.haus"})
        self.assertContains(response, "<title>ACMEid</title>", html=True)
        self.assertContains(response, "Look up a ACMEid")
        self.assertContains(self.client.get("/", {"q": "nope"}, headers={"host": "id.zam.haus"}), "is not a ACMEid", status_code=404)
        self.assertNotContains(response, "ZAM")

    @override_settings(LANGUAGE_CODE="de")
    def test_german_texts_use_the_name(self):
        response = self.client.get("/", headers={"host": "id.zam.haus"})
        self.assertContains(response, "ACMEid nachschlagen")

    def test_inventory_and_admin_use_the_name(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("label_id_info", args=[self.lid.code])), "ACMEid K7R-4XD")
        self.assertContains(self.client.get("/"), "Name, identifier or ACMEid")
        self.assertContains(self.client.get(reverse("admin:inventory_labelid_changelist")), "ACMEids")
