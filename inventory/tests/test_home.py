import json

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["inv.zam.haus", "i.zam.haus", ".example.org"], DEFAULT_DOMAIN="https://inv.zam.haus", DOMAIN_ALIASES=[],
                   LABEL_ID_RESOLVER_HOSTS=["i.zam.haus"], LABEL_ID_BASE_URL="https://i.zam.haus/", LABEL_ID_RESOLVER_URL="https://i.zam.haus/")
class HomePageTests(TestCase):
    def test_search_field_submits_to_item_or_location_search(self):
        response = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"})
        self.assertContains(response, f'<form method="get" action="{reverse("index_items")}" role="search">')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, f'formaction="{reverse("index_locations")}"')
        self.assertContains(response, "data-scan-link")

    def test_scanner_gets_served_hosts(self):
        response = self.client.get(reverse("index"), headers={"host": "inv.zam.haus:8443"})
        self.assertEqual(response.context["scan_hosts"], [".example.org", "i.zam.haus", "inv.zam.haus"])
        self.assertContains(response, '<script id="scan-hosts" type="application/json">')

    @override_settings(DOMAIN_ALIASES=["https://inventory.zam.haus"], LABEL_ID_RESOLVER_URL="https://id.zam.haus/")
    def test_scanner_accepts_earlier_domains_on_old_labels(self):
        response = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"})
        self.assertEqual(response.context["scan_hosts"], [".example.org", "i.zam.haus", "id.zam.haus", "inv.zam.haus", "inventory.zam.haus"])

    @override_settings(ALLOWED_HOSTS=[], DEBUG=True, LABEL_ID_RESOLVER_HOSTS=[], LABEL_ID_BASE_URL="http://localhost:8000/",
                       LABEL_ID_RESOLVER_URL="http://localhost:8000/")
    def test_scanner_always_accepts_the_current_host(self):
        response = self.client.get(reverse("index"), headers={"host": "localhost:8000"})
        self.assertEqual(response.context["scan_hosts"], ["localhost"])

    def test_logout_hides_behind_the_username_on_narrow_screens(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user("ada"))
        content = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"}).content.decode()
        narrow = content.index('<div class="dropdown d-sm-none">')
        self.assertIn('data-bs-toggle="dropdown" aria-expanded="false">ada</button>', content[narrow:])
        self.assertIn('<button class="dropdown-item" type="submit">Logout</button>', content[narrow:])
        self.assertIn('<span class="navbar-text me-2 d-none d-sm-inline">ada</span>', content)

    def test_navbar_scanner_on_every_page(self):
        for url in (reverse("index"), reverse("index_items"), reverse("index_locations")):
            with self.subTest(url=url):
                content = self.client.get(url, headers={"host": "inv.zam.haus"}).content.decode()
                navbar = content[content.index("<nav"):content.index("</nav>")]
                self.assertIn('class="btn btn-sm btn-secondary navbar-scan" data-scan-link disabled', navbar)
                self.assertIn("data-scan-link disabled\n        aria-label=", navbar)
                self.assertIn("</svg></button>", navbar)  # icon only
                self.assertEqual(content.count("inventory/barcode_scanner.js"), 1)
                self.assertEqual(content.count("inventory/link_scanner.js"), 1)
                self.assertIn('<script id="scan-hosts" type="application/json">', content)

    def test_navbar_slides_away_while_scrolling_down(self):
        content = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"}).content.decode()
        self.assertIn('class="navbar navbar-expand-sm bg-light border-bottom sticky-top app-navbar"', content)
        self.assertEqual(content.count("inventory/navbar.js"), 1)
