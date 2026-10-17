from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from inventory.label_ids import access, services

from ..models import LabelIdAccess
from ..label_ids.testing import SETTINGS, InventoryFixture, make_id

BASE = "https://inv.zam.haus"


def with_perms(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="inventory", codename__in=codenames))
    return user


@override_settings(**SETTINGS)
class AccessTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.lid = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.reserved = make_id("5S8B2")
        users = get_user_model().objects
        cls.member = users.create_user(username="ada")
        cls.viewer = with_perms(users.create_user(username="viewer", is_staff=True), "view_labelid")
        cls.reviewer = with_perms(users.create_user(username="reviewer", is_staff=True),
                                  "view_labelid", "view_labelid_access_user")

    def scan(self, path="/K7R4XD", host="i.zam.haus"):
        """Open a label's link like a phone camera would, following the hop into the inventory."""
        response = self.client.get(path, headers={"host": host})
        self.assertEqual(response.status_code, 302)
        url = urlsplit(response["Location"])
        if f"{url.scheme}://{url.netloc}" == BASE and url.query.startswith("via="):
            response = self.client.get(f"{url.path}?{url.query}", headers={"host": "inv.zam.haus"})
        return response

    def record(self, user, method=LabelIdAccess.Method.LABEL_SCAN, local_network=False):
        request = RequestFactory().get("/")
        request.user, request.from_local_network = user, local_network
        access.record(request, self.lid, method)

    def accesses(self, lid=None):
        return list((lid or self.lid).accesses.values_list("method", "user__username"))

    def test_label_scan_records_user_and_resolves(self):
        self.client.force_login(self.member)
        response = self.scan()
        self.assertEqual(response["Location"], self.item.get_absolute_url())
        self.assertEqual(self.accesses(), [("label_scan", "ada")])

    def test_anonymous_label_scan(self):
        self.scan()
        self.assertEqual(self.accesses(), [("label_scan", None)])

    def test_scanning_a_reserved_id_is_recorded_too(self):
        response = self.scan("/5S8B24")
        self.assertEqual(response["Location"], "/id/5S8B24/claim/")
        self.assertEqual(self.accesses(self.reserved), [("label_scan", None)])

    def test_retired_page_is_shown_without_marker_so_reloads_do_not_count(self):
        services.retire(self.lid.code, None)
        response = self.scan()
        self.assertEqual(response["Location"], "/id/K7R4XD")
        for _ in range(2):
            self.assertContains(self.client.get(response["Location"]), "no longer in use", status_code=410)
        self.assertEqual(self.accesses(), [("label_scan", None)])

    def test_typed_urls_and_inventory_links_are_not_recorded(self):
        for host, path in (("i.zam.haus", "/k7r-4xd"), ("id.zam.haus", "/K7R-4XD"), ("inv.zam.haus", "/id/K7R4XD")):
            with self.subTest(host=host, path=path):
                response = self.client.get(path, headers={"host": host})
                self.assertTrue(response["Location"].endswith(self.item.get_absolute_url()))
        self.assertEqual(self.accesses(), [])

    def test_lookup_form_and_search_box_are_web_form_entries(self):
        self.client.force_login(self.member)
        self.scan("/?q=k7r-4xd", host="id.zam.haus")
        response = self.client.get(reverse("index_items"), {"q": "K7R 4XD"})
        self.client.get(response["Location"])
        self.assertEqual(self.accesses(), [("webform", "ada"), ("webform", "ada")])

    def test_only_known_methods_on_get_are_recorded(self):
        self.client.get("/id/K7R4XD", {"via": "admin"})
        self.client.head("/id/K7R4XD", {"via": "label_scan"})
        self.assertEqual(self.accesses(), [])
        self.client.get("/id/K7R4XD", {"via": "webform"})
        self.assertEqual(self.accesses(), [("webform", None)])

    def test_only_the_last_five_are_kept(self):
        for user in (self.member, self.viewer, self.reviewer, self.member, self.viewer, self.reviewer, self.member):
            self.record(user, LabelIdAccess.Method.LABEL_SCAN)
        self.assertEqual([u for _m, u in self.accesses()], ["ada", "reviewer", "viewer", "ada", "reviewer"])
        self.assertEqual(LabelIdAccess.objects.count(), 5)

    @override_settings(LABEL_ID_ACCESS_KEEP=2)
    def test_number_kept_is_configurable(self):
        for user in (self.member, self.viewer, self.reviewer):
            self.record(user, LabelIdAccess.Method.LABEL_SCAN)
        self.assertEqual([u for _m, u in self.accesses()], ["reviewer", "viewer"])

    def test_info_page_shows_user_only_with_permission(self):
        self.record(self.member, LabelIdAccess.Method.LABEL_SCAN)
        self.record(AnonymousUser(), LabelIdAccess.Method.WEBFORM)
        url = reverse("label_id_info", args=["K7R4XD"])
        self.client.force_login(self.viewer)
        response = self.client.get(url)
        self.assertContains(response, "label scan")
        self.assertContains(response, "web form")
        self.assertNotContains(response, "ada")
        self.assertNotContains(response, "not logged in")
        self.client.force_login(self.reviewer)
        response = self.client.get(url)
        self.assertContains(response, "<td>ada</td>", html=True)
        self.assertContains(response, "not logged in")

    def test_zam_network_is_recorded_from_the_address_not_the_group(self):
        middleware = [*SETTINGS["MIDDLEWARE"], "imzam.local_network.LocalNetworkMiddleware"]
        for sources, expected in ((["127.0.0.0/8"], True), (["192.0.2.0/24"], False)):
            with self.subTest(sources=sources), override_settings(MIDDLEWARE=middleware, LOCAL_NETWORK_SOURCES=sources):
                Client().get("/id/K7R4XD", {"via": "label_scan"})  # fresh middleware: it caches the networks
                self.assertEqual(self.lid.accesses.first().local_network, expected)

    def test_info_page_shows_zam_network(self):
        self.record(self.member, local_network=True)
        self.record(self.member)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("label_id_info", args=["K7R4XD"]))
        self.assertContains(response, "<th>at ZAM</th>", html=True)
        self.assertContains(response, "<td>yes</td>", html=True)
        self.assertContains(response, "<td>no</td>", html=True)

    def test_info_page_without_accesses(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("label_id_info", args=["K7R4XD"])), "Not scanned or entered in a web form yet.")

    def test_admin_shows_user_only_with_permission(self):
        self.record(self.member, LabelIdAccess.Method.LABEL_SCAN)
        url = reverse("admin:inventory_labelid_change", args=["K7R4XD"])
        self.client.force_login(self.viewer)
        response = self.client.get(url)
        self.assertContains(response, "label scan")
        self.assertNotContains(response, "<td>ada</td>", html=True)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(url), "<td>ada</td>", html=True)
