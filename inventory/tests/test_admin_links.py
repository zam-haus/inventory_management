import re

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import Item, Location, LocationType, MeasurementUnit, UniqueItem


@override_settings(LANGUAGE_CODE="en")
class AdminLinkTests(TestCase):
    """The navbar's Admin link leads to the admin page of what the page shows (inventory/admin_links.py)."""

    @classmethod
    def setUpTestData(cls):
        room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space")
        cls.room = Location.objects.create(type=room_type, name="Halle", short_name="HAL")
        shelf_type = LocationType.objects.create(name="Regal", unique=True, category="storage_unit")
        cls.shelf = Location.objects.create(type=shelf_type, name="Regal 1", short_name="R1", parent_location=cls.room)
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Drill", kind=Item.Kind.UNIQUE, measurement_unit=unit)
        cls.unique_item = UniqueItem.objects.create(item=cls.item, location=cls.room)
        cls.admin = get_user_model().objects.create_superuser(username="admin")
        cls.helper = get_user_model().objects.create_user(username="helper", is_staff=True)
        cls.helper.user_permissions.add(Permission.objects.get(codename="view_item"))

    def admin_link(self, url):
        page = self.client.get(url).content.decode()
        return re.search(r'class="[^"]*app-menu-admin[^"]*" href="([^"]*)"', page).group(1)

    def test_pages_lead_to_the_admin_page_of_what_they_show(self):
        self.client.force_login(self.admin)
        cases = [
            (self.room.get_absolute_url(), reverse("admin:inventory_location_change", args=[self.room.pk])),
            (self.shelf.get_absolute_url(), reverse("admin:inventory_location_change", args=[self.shelf.pk])),
            (reverse("view_item", args=[self.item.pk]), reverse("admin:inventory_item_change", args=[self.item.pk])),
            (reverse("update_item", args=[self.item.pk]), reverse("admin:inventory_item_change", args=[self.item.pk])),
            (reverse("view_unique_item", args=[self.unique_item.pk]),
             reverse("admin:inventory_uniqueitem_change", args=[self.unique_item.pk])),
            (reverse("create_item"), reverse("admin:inventory_item_add")),
            (reverse("create_unique_item"), reverse("admin:inventory_uniqueitem_add")),
            (reverse("index_items"), reverse("admin:inventory_item_changelist")),
            (reverse("index_locations"), reverse("admin:inventory_location_changelist")),
            (reverse("index"), reverse("admin:index")),
        ]
        if apps.is_installed("maps"):
            cases += [(reverse("maps:map"), reverse("admin:app_list", args=["maps"])),
                      (reverse("maps:plans"), reverse("admin:maps_floorplan_changelist"))]
        for url, expected in cases:
            with self.subTest(url):
                self.assertEqual(self.admin_link(url), expected)

    def test_only_admin_pages_the_user_may_see(self):
        self.client.force_login(self.helper)
        self.assertEqual(self.admin_link(reverse("view_item", args=[self.item.pk])),
                         reverse("admin:inventory_item_change", args=[self.item.pk]))
        # No permission for locations: the admin's start page.
        self.assertEqual(self.admin_link(self.room.get_absolute_url()), reverse("admin:index"))
