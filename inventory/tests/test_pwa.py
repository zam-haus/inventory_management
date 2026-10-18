import json

from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import reverse


class InstallableAppTests(TestCase):
    def test_manifest_points_to_existing_icons(self):
        response = self.client.get(reverse("manifest"))
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        manifest = json.loads(response.content)
        self.assertEqual((manifest["name"], manifest["start_url"], manifest["display"]), ("ZAM-Inventar", "/", "standalone"))
        self.assertEqual(manifest["orientation"], "portrait")
        self.assertEqual({icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"})
        self.assertIn("maskable", [icon.get("purpose") for icon in manifest["icons"]])
        for icon in manifest["icons"]:
            with self.subTest(icon=icon["src"]):
                self.assertTrue(icon["src"].startswith("/static/inventory/favicon/icon-"))
                path, _, version = icon["src"].removeprefix("/static/").partition("?v=")
                self.assertTrue(finders.find(path))
                self.assertTrue(version)  # browsers load a changed icon at once

    @override_settings(DEBUG=True)
    def test_dev_system_manifest(self):
        manifest = json.loads(self.client.get(reverse("manifest")).content)
        self.assertEqual(manifest["name"], "ZAM-Inventar (dev)")
        for icon in manifest["icons"]:
            with self.subTest(icon=icon["src"]):
                self.assertTrue(icon["src"].startswith("/static/inventory/favicon/dev/icon-"))
                path, _, version = icon["src"].removeprefix("/static/").partition("?v=")
                self.assertTrue(finders.find(path))
                self.assertTrue(version)  # browsers load a changed icon at once

    def test_pages_link_manifest_and_service_worker(self):
        for url in (reverse("index_items"), reverse("admin:login")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, f'<link rel="manifest" href="{reverse("manifest")}">', html=True)
                self.assertContains(response, f'navigator.serviceWorker.register("{reverse("service_worker")}")')

    def test_service_worker_caches_only_the_offline_page(self):
        response = self.client.get(reverse("service_worker"))
        self.assertEqual(response["Content-Type"], "text/javascript")
        self.assertIn("no-cache", response["Cache-Control"])
        script = response.content.decode()
        self.assertIn(f'const OFFLINE_URL = "{reverse("offline")}";', script)
        self.assertRegex(script, r'const CACHE = "offline-[0-9a-f]{12}";')
        self.assertEqual(script.count("cache.add("), 1)

    def test_offline_page_is_self_contained(self):
        response = self.client.get(reverse("offline"))
        self.assertContains(response, "Keine Verbindung")
        self.assertContains(response, "<svg")
        self.assertNotContains(response, 'src="')
        self.assertNotContains(response, "stylesheet")

    def test_every_page_offers_pull_to_refresh_in_the_installed_app(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        for url in ("/", reverse("admin:index")):
            with self.subTest(url):
                content = self.client.get(url).content.decode()
                self.assertIn("inventory/pull_refresh.js", content)
                self.assertIn("inventory/pull_refresh.css", content)
                self.assertIn('<meta name="theme-color" content="#f8f9fa">', content)  # the light navbar
                # No status bar workarounds: iOS 27 ignores them (docs/installable-app.md).
                self.assertNotIn("apple-mobile-web-app-status-bar-style", content)
                self.assertNotIn("viewport-fit=cover", content)

    def test_bootstrap_is_served_locally(self):
        response = self.client.get(reverse("index_items"))
        self.assertContains(response, 'href="/static/inventory/vendor/bootstrap/bootstrap.min.css"')
        self.assertContains(response, 'src="/static/inventory/vendor/bootstrap/bootstrap.bundle.min.js"')
        self.assertNotContains(response, "cdn.jsdelivr.net")
        for name in ("bootstrap.min.css", "bootstrap.bundle.min.js"):
            self.assertTrue(finders.find(f"inventory/vendor/bootstrap/{name}"))
