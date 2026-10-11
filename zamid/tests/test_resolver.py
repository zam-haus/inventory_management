from django.test import TestCase, override_settings

from zamid import services

from .helpers import SETTINGS, InventoryFixture, make_id

BASE = "https://inv.zam.haus"
# (host, path pattern, prefix of redirects into the inventory)
ENTRY_POINTS = [
    ("i.zam.haus", "/{}", BASE),
    ("id.zam.haus", "/{}", BASE),
    ("inv.zam.haus", "/id/{}", ""),
]


@override_settings(**SETTINGS)
class ResolverTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.for_item = services.claim(make_id("K7Q4X").code, cls.item, None)
        cls.for_location = services.claim(make_id("12345").code, cls.location, None)
        cls.for_url = services.assign_url(make_id("ABCDE").code, "https://wiki.zam.haus/Laser", None)
        cls.reserved = make_id("5S8B2")
        cls.retired = services.claim(make_id("10000").code, cls.other_item, None)
        services.retire(cls.retired.code, None)

    def each(self, raw, method="get"):
        for host, pattern, base in ENTRY_POINTS:
            with self.subTest(host=host, raw=raw, method=method):
                yield base, getattr(self.client, method)(pattern.format(raw), headers={"host": host})

    def assertRedirect(self, raw, target, *, inventory=True, method="get"):
        for base, response in self.each(raw, method):
            self.assertEqual(response.status_code, 302)  # never 301: targets may change
            self.assertEqual(response["Location"], (base if inventory else "") + target)

    def test_assigned_redirects_to_target(self):
        self.assertRedirect("K7Q4XD", self.item.get_absolute_url())
        self.assertRedirect("123-45V", self.location.get_absolute_url())
        self.assertRedirect("ABCDEM", "https://wiki.zam.haus/Laser", inventory=False)

    def test_reserved_redirects_to_claim(self):
        self.assertRedirect("5S8B2E", "/id/5S8B2E/claim/")

    def test_input_forms_resolve_directly(self):
        for raw in ("k7q4xd", "K7Q-4XD", "k7q-4xd", "K7Q4XD/", "K7Q 4XD", "K7Q.4XD"):
            self.assertRedirect(raw, self.item.get_absolute_url())

    def test_head(self):
        self.assertRedirect("K7Q4XD", self.item.get_absolute_url(), method="head")
        for _base, response in self.each("YYYYYJ", "head"):
            self.assertEqual(response.status_code, 404)

    def test_post_is_not_allowed(self):
        for _base, response in self.each("K7Q4XD", "post"):
            self.assertEqual(response.status_code, 405)

    def test_retired(self):
        for base, response in self.each("100005"):
            self.assertEqual(response.status_code, 410)
            self.assertContains(response, base + self.other_item.get_absolute_url(), status_code=410)

    def test_soft_deleted_target(self):
        self.location.delete()
        for _base, response in self.each("12345V"):
            self.assertContains(response, "No longer in the inventory", status_code=410)
            self.assertNotContains(response, self.location.get_absolute_url(), status_code=410)

    def test_unknown(self):
        for _base, response in self.each("YYYYYJ"):
            self.assertContains(response, "Unknown ID", status_code=404)

    def test_checksum_error_suggests_existing_ids(self):
        for _base, response in self.each("K7Q4XR"):
            self.assertContains(response, "Typo?", status_code=404)
            self.assertContains(response, "K7Q-4XD", status_code=404)

    def test_malformed(self):
        for raw in ("K7Q4X", "hello-world", "%21%21"):
            for _base, response in self.each(raw):
                self.assertContains(response, "Invalid ID", status_code=404)

    def test_lookup_form(self):
        for host, path in (("i.zam.haus", "/"), ("id.zam.haus", "/"), ("inv.zam.haus", "/id/")):
            with self.subTest(host):
                response = self.client.get(path, headers={"host": host})
                self.assertContains(response, 'name="q"')
                response = self.client.get(path, {"q": "k7q-4xd"}, headers={"host": host})
                self.assertRedirects(response, path + "K7Q4XD", fetch_redirect_response=False)
                response = self.client.get(path, {"q": "K7Q4XR"}, headers={"host": host})
                self.assertContains(response, "K7Q-4XD", status_code=404)

    def test_resolver_hosts_serve_nothing_else(self):
        for host in ("i.zam.haus", "id.zam.haus"):
            with self.subTest(host):
                self.assertEqual(self.client.get(self.item.get_absolute_url(), headers={"host": host}).status_code, 404)
                self.assertEqual(self.client.get("/admin/", headers={"host": host}).status_code, 404)
                self.assertContains(self.client.get("/robots.txt", headers={"host": host}), "Disallow: /")
        response = self.client.get(self.item.get_absolute_url(), headers={"host": "inv.zam.haus"})
        self.assertContains(response, "Drill")

    @override_settings(ZAMID_INVENTORY_BASE="https://inventory.example")
    def test_inventory_base_is_configurable(self):
        response = self.client.get("/K7Q4XD", headers={"host": "i.zam.haus"})
        self.assertEqual(response["Location"], "https://inventory.example" + self.item.get_absolute_url())

    @override_settings(ZAMID_MISS_LIMIT=3)
    def test_misses_are_rate_limited(self):
        for raw in ("YYYYYJ", "K7Q4XR", "nope"):
            self.client.get("/" + raw, headers={"host": "i.zam.haus"})
        response = self.client.get("/K7Q4XD", headers={"host": "i.zam.haus"})
        self.assertEqual(response.status_code, 429)

    def test_hits_are_not_rate_limited(self):
        for _ in range(40):
            response = self.client.get("/K7Q4XD", headers={"host": "i.zam.haus"})
        self.assertEqual(response.status_code, 302)
