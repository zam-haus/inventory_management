from urllib.parse import urlsplit

from django.test import TestCase, override_settings

from inventory.label_ids import parsing, services

from ..label_ids.testing import SETTINGS, InventoryFixture, make_id

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
        cls.for_item = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.for_location = services.claim(make_id("12345").code, cls.location, None)
        cls.for_url = services.assign_url(make_id("ABCDE").code, "https://wiki.zam.haus/Laser", None)
        cls.reserved = make_id("5S8B2")
        cls.retired = services.claim(make_id("10000").code, cls.other_item, None)
        services.retire(cls.retired.code, None)

    def request(self, host, path, method="get"):
        """A label scan on a resolver host first visits the inventory to record the access; follow that hop."""
        response = getattr(self.client, method)(path, headers={"host": host})
        location = response.get("Location", "")
        if response.status_code == 302 and location.startswith(BASE + "/id/") and "?via=" in location:
            url = urlsplit(location)
            response = getattr(self.client, method)(f"{url.path}?{url.query}", headers={"host": "inv.zam.haus"})
            if response.status_code == 302 and response["Location"] == url.path:  # retired/deleted: drop ?via=
                response = getattr(self.client, method)(url.path, headers={"host": "inv.zam.haus"})
            return "", response
        return None, response

    def each(self, raw, method="get"):
        for host, pattern, base in ENTRY_POINTS:
            with self.subTest(host=host, raw=raw, method=method):
                hop_base, response = self.request(host, pattern.format(raw), method)
                yield base if hop_base is None else hop_base, response

    def assertRedirect(self, raw, target, *, inventory=True, method="get"):
        for base, response in self.each(raw, method):
            self.assertEqual(response.status_code, 302)  # never 301: targets may change
            self.assertEqual(response["Location"], (base if inventory else "") + target)

    def test_assigned_redirects_to_target(self):
        self.assertRedirect("K7R4XD", self.item.get_absolute_url())
        self.assertRedirect("123-45V", self.location.get_absolute_url())
        self.assertRedirect("ABCDEM", "https://wiki.zam.haus/Laser", inventory=False)

    def test_item_labels_pass_the_location_on(self):
        """Item labels hold the item's ID and the location's code (…/K7R4XD/WS); it reaches the item's page."""
        item_url, loc = self.item.get_absolute_url(), self.location.pk
        code = self.location.unique_identifier
        self.assertRedirect(f"K7R4XD/{code.upper()}", f"{item_url}?loc={loc}")
        self.assertRedirect(f"K7R4XD/{code.lower()}", f"{item_url}?loc={loc}")
        self.assertRedirect("K7R4XD/NOWHERE", item_url)  # an unknown location is left out
        self.assertRedirect(f"ABCDEM/{code}", "https://wiki.zam.haus/Laser", inventory=False)  # not elsewhere
        self.assertEqual(parsing.code_from_scan(f"HTTPS://I.ZAM.HAUS/K7R4XD/{code}"), "K7R4XD")

    def test_reserved_redirects_to_claim(self):
        self.assertRedirect("5S8B24", "/id/5S8B24/claim/")

    def test_input_forms_resolve_directly(self):
        for raw in ("k7r4xd", "K7R-4XD", "k7r-4xd", "K7R4XD/", "K7R 4XD", "K7R.4XD"):
            self.assertRedirect(raw, self.item.get_absolute_url())

    def test_head(self):
        self.assertRedirect("K7R4XD", self.item.get_absolute_url(), method="head")
        for _base, response in self.each("YYYYYJ", "head"):
            self.assertEqual(response.status_code, 404)

    def test_post_is_not_allowed(self):
        for _base, response in self.each("K7R4XD", "post"):
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
        for _base, response in self.each("K7R4XR"):
            self.assertContains(response, "Typo?", status_code=404)
            self.assertContains(response, "K7R-4XD", status_code=404)

    def test_malformed(self):
        for raw in ("K7R4X", "hello-world", "%21%21"):
            for _base, response in self.each(raw):
                self.assertContains(response, "Invalid ID", status_code=404)

    def test_lookup_form(self):
        for host, path in (("i.zam.haus", "/"), ("id.zam.haus", "/"), ("inv.zam.haus", "/id/")):
            with self.subTest(host):
                response = self.client.get(path, headers={"host": host})
                self.assertContains(response, 'name="q"')
                response = self.client.get(path, {"q": "k7r-4xd"}, headers={"host": host})
                base = "" if host == "inv.zam.haus" else BASE
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(base + "/id/K7R4XD?via="), response["Location"])
                response = self.client.get(path, {"q": "K7R4XR"}, headers={"host": host})
                self.assertContains(response, "K7R-4XD", status_code=404)

    def test_resolver_hosts_serve_nothing_else(self):
        for host in ("i.zam.haus", "id.zam.haus"):
            with self.subTest(host):
                self.assertEqual(self.client.get(self.item.get_absolute_url(), headers={"host": host}).status_code, 404)
                self.assertEqual(self.client.get("/admin/", headers={"host": host}).status_code, 404)
                self.assertContains(self.client.get("/robots.txt", headers={"host": host}), "Disallow: /")
        response = self.client.get(self.item.get_absolute_url(), headers={"host": "inv.zam.haus"})
        self.assertContains(response, "Drill")

    def test_favicon_on_every_host(self):
        for host in ("i.zam.haus", "id.zam.haus", "inv.zam.haus"):
            for name, content_type in (("favicon.ico", "image/x-icon"), ("favicon.svg", "image/svg+xml")):
                with self.subTest(host=host, name=name):
                    response = self.client.get(f"/{name}", headers={"host": host})
                    self.assertEqual((response.status_code, response["Content-Type"]), (200, content_type))
                    self.assertIn("public", response["Cache-Control"])
        self.assertContains(self.client.get("/", headers={"host": "id.zam.haus"}), 'href="/favicon.svg"')

    @override_settings(LABEL_ID_INVENTORY_BASE="https://inventory.example")
    def test_inventory_base_is_configurable(self):
        response = self.client.get("/K7R4XD", headers={"host": "i.zam.haus"})
        self.assertTrue(response["Location"].startswith("https://inventory.example/id/K7R4XD?via="))
        response = self.client.get("/k7r-4xd", headers={"host": "i.zam.haus"})
        self.assertEqual(response["Location"], "https://inventory.example" + self.item.get_absolute_url())

    @override_settings(LABEL_ID_MISS_LIMIT=3)
    def test_misses_are_rate_limited(self):
        for raw in ("YYYYYJ", "K7R4XR", "nope"):
            self.client.get("/" + raw, headers={"host": "i.zam.haus"})
        response = self.client.get("/K7R4XD", headers={"host": "i.zam.haus"})
        self.assertEqual(response.status_code, 429)

    def test_hits_are_not_rate_limited(self):
        for _ in range(40):
            response = self.client.get("/K7R4XD", headers={"host": "i.zam.haus"})
        self.assertEqual(response.status_code, 302)
