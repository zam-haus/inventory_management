from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ..label_ids import services
from ..label_ids.testing import MIDDLEWARE, SETTINGS, InventoryFixture, make_id

HOSTS = dict(
    SETTINGS,
    MIDDLEWARE=["imzam.canonical_host.CanonicalHostMiddleware", *MIDDLEWARE],
    ALLOWED_HOSTS=["testserver", "inventar.zam.haus", "inv.zam.haus", "i.zam.haus", "id.zam.haus"],
    DEFAULT_URL="https://inventar.zam.haus",
    DOMAIN_ALIASES=["https://inv.zam.haus"],
    LABEL_ID_RESOLVER_URL="https://id.zam.haus/",
    CANONICAL_HOST_REDIRECT=True,
)


@override_settings(**HOSTS)
class CanonicalHostTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.lid = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.member = get_user_model().objects.create_user(username="ada")

    def get(self, path, host, **kwargs):
        return self.client.get(path, headers={"host": host}, **kwargs)

    def test_other_domains_redirect_to_the_main_one_keeping_path_and_query(self):
        for host in ("inv.zam.haus", "inventory.betreiberverein.de", "unknown.example.org"):  # also outside ALLOWED_HOSTS
            with self.subTest(host=host):
                response = self.get("/loc/1/N1?x=1", host)
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], "https://inventar.zam.haus/loc/1/N1?x=1")

    def test_posts_keep_their_method(self):
        response = self.client.post("/accounts/login/", {"username": "ada"}, headers={"host": "inv.zam.haus"})
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "https://inventar.zam.haus/accounts/login/")

    def test_main_domains_and_development_hosts_are_served(self):
        for host in ("inventar.zam.haus", "testserver", "localhost:8000", "127.0.0.1", "[::1]:8000", "192.168.178.10"):
            with self.subTest(host=host):
                with self.settings(ALLOWED_HOSTS=["*"]):
                    self.assertEqual(self.get(self.item.get_absolute_url(), host).status_code, 200)

    def test_can_be_turned_off(self):
        with self.settings(CANONICAL_HOST_REDIRECT=False):
            self.assertEqual(self.get(self.item.get_absolute_url(), "inv.zam.haus").status_code, 200)

    def test_resolver_aliases_redirect_to_the_main_resolver(self):
        for path in ("/", "/?q=K7R4XD", "/k7r4xd", "/K7R4XD/", "/robots.txt"):
            with self.subTest(path=path):
                response = self.get(path, "i.zam.haus")
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], "https://id.zam.haus" + path)

    def test_label_scans_on_the_qr_host_go_straight_to_the_inventory(self):
        response = self.get("/K7R4XD", "i.zam.haus")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://inventar.zam.haus/id/K7R4XD?via=label_scan")

    def test_scan_tracking_survives_the_redirects(self):
        """A scan recorded with the user logged in on the main domain, whichever host the label names."""
        self.client.force_login(self.member)
        for scanned_host in ("i.zam.haus", "id.zam.haus"):
            with self.subTest(host=scanned_host):
                url = urlsplit(self.get("/K7R4XD", scanned_host)["Location"])
                self.assertEqual((url.netloc, url.query), ("inventar.zam.haus", "via=label_scan"))
                response = self.get(f"{url.path}?{url.query}", url.netloc)
                self.assertEqual(response["Location"], self.item.get_absolute_url())
        # An earlier inventory domain in between keeps the marker, too.
        response = self.get("/id/K7R4XD?via=label_scan", "inv.zam.haus")
        self.assertEqual(response["Location"], "https://inventar.zam.haus/id/K7R4XD?via=label_scan")
        self.get("/id/K7R4XD?via=label_scan", "inventar.zam.haus")
        self.assertEqual(list(self.lid.accesses.values_list("method", "user__username")), [("label_scan", "ada")] * 3)

    def test_address_settings_accept_bare_domains(self):
        from imzam.settings import with_scheme
        self.assertEqual(with_scheme("inventar.zam.haus"), "https://inventar.zam.haus")
        self.assertEqual(with_scheme(" http://localhost:8000 "), "http://localhost:8000")
        self.assertEqual(with_scheme(""), "")

    def test_label_id_links_inside_the_inventory_stay_there(self):
        # Sending them to id.zam.haus would come back as a label scan.
        response = self.get("/id/K7R4XD", "inventar.zam.haus")
        self.assertEqual(response["Location"], self.item.get_absolute_url())
        self.assertFalse(self.lid.accesses.exists())
