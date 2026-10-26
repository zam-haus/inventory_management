from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import ChangeLog, Location, LocationFormerCode, LocationNumberRange, LocationType


@override_settings(LANGUAGE_CODE="en")
class ContainerCreateTests(TestCase):
    """Boxes, cartons and pallets are added on the inventory pages with the next number of their type."""

    @classmethod
    def setUpTestData(cls):
        room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space",
                                                admin_only=True)
        numeric = {"unique": True, "moveable": True, "category": "container", "auto_sequence": "0123456789"}
        cls.box_type = LocationType.objects.create(name="Kiste", auto_name_prefix="Kiste", auto_short_name_prefix="K",
                                                   auto_short_name_padding_length=4, no_sublocations=True, **numeric)
        cls.carton_type = LocationType.objects.create(name="Karton", auto_name_prefix="Karton",
                                                      auto_short_name_prefix="Ka", auto_short_name_padding_length=5,
                                                      no_sublocations=True, **numeric)
        cls.pallet_type = LocationType.objects.create(name="Palette", auto_name_prefix="Palette",
                                                      auto_short_name_prefix="P", auto_short_name_padding_length=4,
                                                      **numeric)
        cls.shelf_type = LocationType.objects.create(
            name="Regal", unique=True, area_numbering=True, moveable=True, category="storage_unit",
            auto_name_prefix="Regal", auto_short_name_prefix="R", auto_short_name_padding_length=3,
            auto_sequence="0123456789")
        cls.hall = Location.objects.create(type=room_type, name="Halle", short_name="HAL")
        LocationNumberRange.objects.create(location=cls.hall, type=cls.shelf_type, first=300, last=309)
        # Older boxes were numbered hexadecimally; such codes do not count, digits-only ones do.
        for short in ("K034c", "K0524"):
            Location.objects.create(type=cls.box_type, name=f"Kiste {short[1:]}", short_name=short,
                                    parent_location=cls.hall)
        Location.objects.create(type=cls.carton_type, name="Karton 394", short_name="Ka00394", parent_location=cls.hall)
        cls.box = Location.objects.get(short_name="K0524")
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["add_location", "change_location"]))
        cls.viewer = get_user_model().objects.create_user(username="viewer")

    def url(self, parent):
        return reverse("container_create", args=[parent.pk])

    def test_next_numbers_count_up_per_type(self):
        self.assertEqual(self.box_type.next_free_number(), (525, "Kiste 525", "K0525"))
        self.assertEqual(self.carton_type.next_free_number(), (395, "Karton 395", "Ka00395"))
        self.assertEqual(self.pallet_type.next_free_number(), (1, "Palette 1", "P0001"))
        # Former codes count as used, too.
        LocationFormerCode.objects.create(code="K0530")
        self.assertEqual(self.box_type.next_free_number()[2], "K0531")

    def test_container_is_created_with_purpose_and_description(self):
        self.client.force_login(self.member)
        page = self.client.get(self.url(self.hall)).content.decode()
        for choice in ("Kiste · K0525", "Karton · Ka00395", "Palette · P0001"):
            self.assertIn(choice, page)
        self.assertNotIn('name="wish"', page)  # no number to choose
        response = self.client.post(self.url(self.hall), {
            "type": self.box_type.pk, "purpose": "Karpfenprojekt", "physical_description": "blaue Eurobox 60×40",
        })
        box = Location.objects.get(short_name="K0525")
        self.assertRedirects(response, box.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((box.name, box.parent_location, box.purpose, box.physical_description),
                         ("Kiste 525", self.hall, "Karpfenprojekt", "blaue Eurobox 60×40"))
        self.assertTrue(ChangeLog.objects.filter(location=box, other_location=self.hall, action="created", actor=self.member).exists())
        self.client.post(self.url(self.hall), {"type": self.box_type.pk})
        self.assertTrue(Location.objects.filter(short_name="K0526").exists())

    def test_a_number_taken_in_the_meantime_is_skipped(self):
        self.client.force_login(self.member)
        original = Location.save
        calls = []

        def taken_once(location, *args, **kwargs):
            if location.pk is None and not calls:
                calls.append(location.short_name)
                raise IntegrityError
            return original(location, *args, **kwargs)

        with patch.object(Location, "save", taken_once):
            self.client.post(self.url(self.hall), {"type": self.pallet_type.pk})
        self.assertEqual(calls, ["P0001"])
        self.assertTrue(Location.objects.filter(short_name="P0001").exists())

    def test_several_at_once_get_the_next_numbers(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.url(self.hall)), 'name="count"')
        response = self.client.post(self.url(self.hall), {"type": self.box_type.pk, "count": 3, "purpose": "Lager"})
        self.assertRedirects(response, self.hall.get_absolute_url(), fetch_redirect_response=False)
        boxes = Location.objects.filter(short_name__in=["K0525", "K0526", "K0527"])
        self.assertEqual([(box.parent_location, box.purpose) for box in boxes], [(self.hall, "Lager")] * 3)
        self.assertEqual(self.client.post(self.url(self.hall), {"type": self.box_type.pk, "count": 51}).status_code,
                         200)  # at most 50 at a time
        # One invalid container creates none of them.
        with patch.object(Location, "full_clean", side_effect=[None, ValidationError("broken")]):
            response = self.client.post(self.url(self.hall), {"type": self.box_type.pk, "count": 2})
        self.assertContains(response, "broken")
        self.assertFalse(Location.objects.filter(short_name="K0528").exists())

    def test_location_pages_show_the_path(self):
        pallet = Location.objects.create(type=self.pallet_type, name="Palette 1", short_name="P0001",
                                         parent_location=self.hall)
        self.client.force_login(self.member)
        page = self.client.get(self.url(pallet)).content.decode()
        for location in (self.hall, pallet):  # title and short name as a code chip (docs/locations.md)
            self.assertInHTML(f'<a href="{location.get_absolute_url()}"><span class="loc-label"><span class="loc-title">'
                              f'{location.name}</span> <span class="loc-code" data-location-info="{location.pk}" '
                              f'role="button" tabindex="0" title="Location in brief">{location.short_name}</span></span></a>', page)
        breadcrumb = page[page.index('class="location-breadcrumb"'):page.index("</nav>", page.index("location-breadcrumb"))]
        self.assertNotIn(f'href="{reverse("index_locations")}"', breadcrumb)  # no "Locations" at the root

    def test_boxes_take_no_containers(self):
        self.client.force_login(self.member)
        self.assertEqual(self.box.container_types(), [])
        self.assertEqual(self.client.get(self.url(self.box)).status_code, 403)
        self.assertNotContains(self.client.get(self.box.get_absolute_url()), self.url(self.box))

    def test_buttons_on_the_location_page(self):
        self.assertNotContains(self.client.get(self.hall.get_absolute_url()), self.url(self.hall))  # guests
        self.client.force_login(self.viewer)
        page = self.client.get(self.hall.get_absolute_url()).content.decode()
        self.assertNotIn(f'href="{self.url(self.hall)}"', page)
        self.assertIn("Add a box, carton or pallet with the next number", page)  # disabled, with its reason
        self.client.force_login(self.member)
        page = self.client.get(self.hall.get_absolute_url()).content.decode()
        self.assertIn(f'href="{self.url(self.hall)}"', page)
        self.assertIn("Karton / Kiste / Palette", page)

    def test_an_empty_containers_panel_shows_for_logged_in_users(self):
        pallet = Location.objects.create(type=self.pallet_type, name="Palette 1", short_name="P0001",
                                         parent_location=self.hall)
        self.client.force_login(self.member)
        page = self.client.get(pallet.get_absolute_url()).content.decode()
        self.assertIn('id="location-children-container"', page)
        self.assertIn(f'href="{self.url(pallet)}"', page)

    def test_shelves_get_a_physical_description_too(self):
        self.client.force_login(self.member)
        url = reverse("numbered_location_create", args=[self.hall.pk])
        self.assertContains(self.client.get(url, {"type": self.shelf_type.pk}), 'name="physical_description"')
        self.client.post(url, {"type": self.shelf_type.pk, "mode": "reserved", "reserved": "300",
                               "physical_description": "Schwerlastregal, 5 Böden"})
        self.assertEqual(Location.objects.get(short_name="R300").physical_description, "Schwerlastregal, 5 Böden")
