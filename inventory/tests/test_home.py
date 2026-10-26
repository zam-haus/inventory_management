import json

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["inv.zam.haus", "i.zam.haus", ".example.org"], DEFAULT_URL="https://inv.zam.haus", DOMAIN_ALIASES=[],
                   LABEL_ID_RESOLVER_HOSTS=["i.zam.haus"], LABEL_ID_BASE_URL="https://i.zam.haus/", LABEL_ID_RESOLVER_URL="https://i.zam.haus/")
class HomePageTests(TestCase):
    def test_the_home_page_is_the_search(self):
        response = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"})
        self.assertContains(response, 'data-live-search')
        self.assertContains(response, 'name="q"')
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

    def test_navbar_menus(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user("ada", is_staff=True))
        content = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"}).content.decode()
        navbar = content[content.index("<nav"):content.index("</nav>")]
        # Items and Locations with the icons of their kinds (narrow screens: the icon only, the name for screen readers).
        nav = navbar[navbar.index('<ul class="navbar-nav app-nav">'):navbar.index("</ul>")]
        self.assertIn('class="bi bi-boxes"', nav)
        self.assertIn('class="bi bi-geo-alt"', nav)
        self.assertIn('<span class="app-nav-label">Sachen</span>', nav)
        # The … menu: the names, Admin and the user with Logout (wider screens: Admin in the bar).
        menu = navbar[navbar.index('<div class="dropdown app-menu">'):navbar.index('<div class="dropdown d-none d-sm-block">')]
        self.assertIn('aria-label="Menü"', menu)
        self.assertIn("<span>Sachen</span>", menu)
        self.assertIn("<span>Standorte</span>", menu)
        self.assertIn('class="dropdown-item action-menu-item app-menu-admin" href="/admin/"', menu)
        self.assertIn('<h6 class="dropdown-header app-menu-narrow">ada</h6>', menu)
        self.assertIn("<span>Logout</span></button>", menu)
        # Wider screens: Logout behind the username, right of Admin.
        user = navbar[navbar.index('<div class="dropdown d-none d-sm-block">'):]
        self.assertIn('data-bs-toggle="dropdown" aria-expanded="false">ada</button>', user)
        self.assertIn('<button class="dropdown-item" type="submit">Logout</button>', user)

    def test_navbar_for_guests(self):
        content = self.client.get(reverse("index"), headers={"host": "inv.zam.haus"}).content.decode()
        navbar = content[content.index("<nav"):content.index("</nav>")]
        self.assertIn(">Login</a>", navbar)
        self.assertIn("<span>Sachen</span>", navbar)
        self.assertNotIn("Admin", navbar)
        self.assertNotIn("Logout", navbar)

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
        self.assertIn('class="navbar navbar-expand bg-light border-bottom sticky-top app-navbar"', content)
        self.assertEqual(content.count("inventory/navbar.js"), 1)
