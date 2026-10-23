from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import Location, LocationNumberRange, LocationType

COMPUTED = ["unique_identifier", "locatable_identifier", "descriptive_identifier"]


@override_settings(LANGUAGE_CODE="en")
class StorageUnitsOnPalletsTests(TestCase):
    """Shelves and cabinets stand in a level, room or area, or on a pallet there, and can be moved."""

    @classmethod
    def setUpTestData(cls):
        room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space",
                                                admin_only=True)
        cls.compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach",
                                                      auto_sequence="abcdefghijklmnopqrstuvwxyz",
                                                      category="storage_unit")
        cls.shelf_type = LocationType.objects.create(
            name="Regal", unique=True, area_numbering=True, moveable=True, category="storage_unit",
            auto_name_prefix="Regal", auto_short_name_prefix="R", auto_short_name_padding_length=3,
            auto_sequence="0123456789", sublocation_type=cls.compartment)
        cls.pallet_type = LocationType.objects.create(name="Palette", unique=True, moveable=True, category="container")
        box_type = LocationType.objects.create(name="Kiste", unique=True, moveable=True, category="container",
                                               no_sublocations=True)
        cls.hall = Location.objects.create(type=room_type, name="Halle", short_name="HAL")
        cls.store = Location.objects.create(type=room_type, name="Lager", short_name="LAG")
        LocationNumberRange.objects.create(location=cls.hall, type=cls.shelf_type, first=300, last=309)
        cls.pallet = Location.objects.create(type=cls.pallet_type, name="Palette 1", short_name="P0001",
                                             parent_location=cls.hall)
        cls.loose_pallet = Location.objects.create(type=cls.pallet_type, name="Palette 2", short_name="P0002")
        cls.box = Location.objects.create(type=box_type, name="Kiste 1", short_name="K0001", parent_location=cls.hall)
        cls.shelf = Location.objects.create(type=cls.shelf_type, name="Regal 300", short_name="R300",
                                            parent_location=cls.hall)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["add_location", "change_location"]))

    def setUp(self):
        self.client.force_login(self.member)

    def create_url(self, parent):
        return reverse("numbered_location_create", args=[parent.pk])

    def test_a_pallet_in_a_room_offers_shelves_with_the_rooms_numbers(self):
        self.assertEqual(self.pallet.numbering_area(), self.hall)
        self.assertEqual([kind for kind, _source in self.pallet.numbering_types()], [self.shelf_type])
        self.assertContains(self.client.get(self.pallet.get_absolute_url()), self.create_url(self.pallet))
        self.client.post(self.create_url(self.pallet), {"type": self.shelf_type.pk, "mode": "reserved",
                                                        "reserved": "301", "sublocations": 2})
        shelf = Location.objects.get(short_name="R301")
        self.assertEqual(shelf.parent_location, self.pallet)
        self.assertEqual(sorted(shelf.children.values_list("name", flat=True)), ["Regal 301 Fach a", "Regal 301 Fach b"])

    def test_numbers_are_reserved_for_the_room_not_the_pallet(self):
        LocationNumberRange.objects.all().delete()
        self.client.post(self.create_url(self.pallet), {"type": self.shelf_type.pk, "mode": "auto", "expected": 5})
        self.assertEqual(list(LocationNumberRange.objects.values_list("location", flat=True)), [self.hall.pk])
        self.client.post(self.create_url(self.pallet), {"type": self.shelf_type.pk, "mode": "wish", "wish": 700,
                                                        "expected": 3})
        self.assertEqual(LocationNumberRange.objects.get(first=700).location, self.hall)
        self.assertEqual(Location.objects.get(short_name="R700").parent_location, self.pallet)

    def test_a_pallet_outside_the_building_and_a_box_offer_nothing(self):
        self.assertEqual(self.loose_pallet.numbering_types(), [])
        self.assertEqual(self.box.numbering_types(), [])
        self.assertEqual(self.client.get(self.create_url(self.loose_pallet)).status_code, 403)
        self.assertNotContains(self.client.get(self.loose_pallet.get_absolute_url()), self.create_url(self.loose_pallet))

    def test_shelves_move_onto_a_pallet_and_into_another_room_but_not_into_a_shelf(self):
        for destination in (self.pallet, self.store):
            with self.subTest(destination=destination.name):
                response = self.client.post(reverse("location_move", args=[self.shelf.pk]),
                                            {"parent_location": destination.pk, "id": self.shelf.pk})
                self.assertEqual(response.status_code, 302)
                self.shelf.refresh_from_db()
                self.assertEqual(self.shelf.parent_location, destination)
                self.assertEqual(self.shelf.short_name, "R300")  # it keeps its number
        other = Location.objects.create(type=self.shelf_type, name="Regal 301", short_name="R301",
                                        parent_location=self.hall)
        compartment = Location.objects.create(type=self.compartment, name="Fach a", short_name="a",
                                              parent_location=other)
        # Not without a place either; the dialog does not offer the top level for shelves.
        response = self.client.post(reverse("location_move", args=[self.shelf.pk]), {"parent_location": "", "id": self.shelf.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(self.client.get(self.shelf.get_absolute_url()), "Leave the destination empty")
        self.assertIsNotNone(Location.objects.get(pk=self.shelf.pk).parent_location)
        for destination in (other, compartment):
            self.shelf.parent_location = destination
            with self.subTest(destination=destination.name), self.assertRaises(ValidationError):
                self.shelf.full_clean(exclude=COMPUTED)

    def test_move_here_on_a_pallet_takes_shelves(self):
        response = self.client.post(reverse("locations_move_here", args=[self.pallet.pk]), {"identifiers": "R300"})
        self.assertEqual(response.status_code, 302)
        self.shelf.refresh_from_db()
        self.assertEqual(self.shelf.parent_location, self.pallet)

    def test_destinations_offered_for_a_shelf(self):
        compartment = Location.objects.create(type=self.compartment, name="Fach a", short_name="a",
                                              parent_location=self.shelf)
        other = Location.objects.create(type=self.shelf_type, name="Regal 302", short_name="R302",
                                        parent_location=self.hall)
        response = self.client.get(reverse("parent_location_autocomplete"),
                                   {"forward": f'{{"id": "{other.pk}"}}'})
        ids = {int(result["id"]) for result in response.json()["results"]}
        self.assertIn(self.pallet.pk, ids)
        self.assertIn(self.store.pk, ids)
        self.assertNotIn(self.shelf.pk, ids)
        self.assertNotIn(compartment.pk, ids)

    def test_a_pallet_moves_with_its_shelf(self):
        self.shelf.parent_location = self.pallet
        self.shelf.save()
        response = self.client.post(reverse("location_move", args=[self.pallet.pk]),
                                    {"parent_location": self.store.pk, "id": self.pallet.pk})
        self.assertEqual(response.status_code, 302)
        self.shelf.refresh_from_db()
        self.assertEqual(self.shelf.locatable_identifier, "LAG.P0001.R300")
