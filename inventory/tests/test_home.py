import json

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["inv.zam.haus", "i.zam.haus", ".example.org"])
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

    @override_settings(ALLOWED_HOSTS=[], DEBUG=True)
    def test_scanner_always_accepts_the_current_host(self):
        response = self.client.get(reverse("index"), headers={"host": "localhost:8000"})
        self.assertEqual(response.context["scan_hosts"], ["localhost"])
