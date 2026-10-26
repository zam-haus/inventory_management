from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from ..location_lookup import resolve_location_reference
from ..models import Location, LocationFormerCode, LocationNumberRange, LocationType
from ..models.location import taken_location_codes


class CodeTypesMixin:
    @classmethod
    def setUpTestData(cls):
        cls.room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space",
                                                    admin_only=True)
        cls.compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach",
                                                      auto_sequence="abcdefghijklmnopqrstuvwxyz",
                                                      category="storage_unit", deletable_in_frontend=True)
        naming = {"unique": True, "area_numbering": True, "moveable": True, "category": "storage_unit",
                  "auto_short_name_padding_length": 3, "auto_sequence": "0123456789", "sublocation_type": cls.compartment}
        cls.shelf_type = LocationType.objects.create(name="Regal", auto_name_prefix="Regal", auto_short_name_prefix="R",
                                                     **naming)
        cls.cabinet_type = LocationType.objects.create(name="Schrank", auto_name_prefix="Schrank",
                                                       auto_short_name_prefix="S", **naming)
        cls.room = Location.objects.create(type=cls.room_type, name="Halle", short_name="HAL")
        cls.shelf = Location.objects.create(type=cls.shelf_type, name="Regal 301", short_name="R301",
                                            parent_location=cls.room)
        for name, code in cls.compartment.free_sublocation_names(cls.shelf, 2):
            Location.objects.create(type=cls.compartment, name=name, short_name=code, parent_location=cls.shelf)
        LocationNumberRange.objects.create(location=cls.room, type=cls.shelf_type, first=300, last=309)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["add_location", "change_location"]))

    def rename(self, location, short_name):
        location.short_name = short_name
        location.full_clean(exclude=["unique_identifier", "locatable_identifier", "descriptive_identifier"])
        location.save()


class FormerCodeTests(CodeTypesMixin, TestCase):
    """Codes are meant to stay: a changed one stays blocked as a former code and still finds its location."""

    def test_a_new_short_name_keeps_the_old_codes_of_the_location_and_its_compartments(self):
        self.rename(self.shelf, "R399")
        former = dict(LocationFormerCode.objects.values_list("code", "location_id"))
        compartment_a = self.shelf.children.get(short_name="a")
        self.assertEqual(former["R301"], self.shelf.pk)
        self.assertEqual(former["R301.a"], compartment_a.pk)
        self.assertIn("R301.b", former)
        self.assertEqual(Location.objects.get(pk=compartment_a.pk).unique_identifier, "R399.a")

    def test_moving_a_shelf_keeps_its_code(self):
        other = Location.objects.create(type=self.room_type, name="Lager", short_name="LAG")
        self.shelf.parent_location = other
        self.shelf.save()
        self.assertFalse(LocationFormerCode.objects.exists())

    def test_former_codes_find_their_location(self):
        self.rename(self.shelf, "R399")
        self.assertEqual(resolve_location_reference("R301"), self.shelf)
        self.assertEqual(resolve_location_reference("R301.a"), self.shelf.children.get(short_name="a"))
        # A code typed into the search leads to its location, also a former one.
        response = self.client.get(reverse("index"), {"q": "r301"})
        self.assertRedirects(response, self.shelf.get_absolute_url(), fetch_redirect_response=False)
        response = self.client.get(reverse("location-autocomplete"), {"q": "R301"})
        self.assertContains(response, f'"id": "{self.shelf.pk}"')
        page = self.client.get(self.shelf.get_absolute_url()).content.decode()
        self.assertIn("R301", page[page.index('id="location-metadata"'):])

    def test_blocked_codes_are_not_given_again(self):
        self.rename(self.shelf, "R399")
        # Neither as a reserved number nor as a new short name.
        self.assertNotIn("R301", [short for _n, _name, short in self.room.free_numbers(self.shelf_type)])
        self.assertIn(301, LocationNumberRange.unavailable(self.shelf_type, 301, 301))
        new = Location(type=self.shelf_type, name="Regal 301", short_name="R301", parent_location=self.room)
        with self.assertRaisesMessage(ValidationError, "R301"):
            new.full_clean(exclude=["unique_identifier", "locatable_identifier", "descriptive_identifier"])
        other = Location.objects.create(type=self.shelf_type, name="Regal 302", short_name="R302",
                                        parent_location=self.room)
        with self.assertRaises(ValidationError):
            self.rename(other, "R301")

    def test_compartment_letters_of_a_former_code_are_skipped(self):
        compartment_b = self.shelf.children.get(short_name="b")
        compartment_b.parent_location = Location.objects.create(type=self.shelf_type, name="Regal 302",
                                                                short_name="R302", parent_location=self.room)
        compartment_b.save()  # its code R301.b is kept blocked
        self.assertEqual([code for _name, code in self.compartment.free_sublocation_names(self.shelf, 1)], ["c"])

    def test_renaming_back_uses_the_former_code_again(self):
        self.rename(self.shelf, "R399")
        self.rename(self.shelf, "R301")
        self.assertEqual(set(LocationFormerCode.objects.values_list("code", flat=True)), {"R399", "R399.a", "R399.b"})

    def test_deleting_for_good_keeps_the_code_blocked(self):
        box_type = LocationType.objects.create(name="Kiste", unique=True, moveable=True, category="container",
                                               no_sublocations=True, auto_name_prefix="Kiste",
                                               auto_short_name_prefix="K", auto_short_name_padding_length=4,
                                               auto_sequence="0123456789")
        box = Location.objects.create(type=box_type, name="Kiste 1", short_name="K0001", parent_location=self.room)
        box.delete()
        self.assertFalse(LocationFormerCode.objects.exists())  # soft deletion keeps the location and its code
        Location.objects.get(pk=box.pk).delete()
        self.assertTrue(LocationFormerCode.objects.filter(code="K0001", location=None).exists())
        self.assertEqual(box_type.next_free_number(), (2, "Kiste 2", "K0002"))

    def test_a_current_code_cannot_be_added_as_former_code(self):
        with self.assertRaises(ValidationError):
            LocationFormerCode(code="R301").full_clean()
        LocationFormerCode(code="R300", note="old label").full_clean()

    def test_frontend_never_changes_a_short_name(self):
        self.client.force_login(self.member)
        posts = [
            (reverse("location_purpose_update", args=[self.shelf.pk]), {"purpose": "Leim", "short_name": "X1"}),
            (reverse("location_overview_update", args=[self.shelf.pk]), {"short_name": "X1"}),
            (reverse("location_move", args=[self.shelf.pk]), {"parent_location": self.room.pk, "short_name": "X1"}),
        ]
        for url, data in posts:
            with self.subTest(url=url):
                self.client.post(url, data)
        self.assertEqual(Location.objects.get(pk=self.shelf.pk).short_name, "R301")
        self.assertFalse(LocationFormerCode.objects.exists())


@override_settings(LANGUAGE_CODE="en")
class CodesIgnoringCaseTests(CodeTypesMixin, TestCase):
    """Labels hold codes in capitals: codes differ in more than capital and small letters, in the model (clean)
    and in the database."""
    EXCLUDE = ["unique_identifier", "locatable_identifier", "descriptive_identifier"]

    def assertRefused(self, location, message):
        with self.assertRaisesMessage(ValidationError, message):
            location.full_clean(exclude=self.EXCLUDE)

    def test_codes_that_differ_only_in_case_are_refused(self):
        self.assertRefused(Location(type=self.compartment, name="Fach A", short_name="A", parent_location=self.shelf),
                           "unique among all sibling locations")
        self.assertRefused(Location(type=self.shelf_type, name="Regal", short_name="r301", parent_location=self.room),
                           "Short name must be unique")
        self.assertRefused(Location(type=self.room_type, name="Ecke", short_name="r301.A"),
                           "The code r301.A is too close to R301.a")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Location.objects.create(type=self.compartment, name="Fach A", short_name="A", parent_location=self.shelf)

    def test_former_codes_ignore_case_too(self):
        self.rename(self.shelf, "R399")
        self.assertRefused(Location(type=self.shelf_type, name="Regal 301", short_name="r301", parent_location=self.room),
                           "was used before")
        self.assertEqual(taken_location_codes(["r301", "R302", "r399"]), {"r301", "r399"})
        with self.assertRaises(ValidationError):
            LocationFormerCode(code="r399").full_clean()  # the shelf's current code
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocationFormerCode.objects.create(code="r301")

    def test_a_change_of_case_only_keeps_no_former_code(self):
        self.rename(self.shelf, "r301")
        self.assertEqual(Location.objects.get(pk=self.shelf.pk).unique_identifier, "r301")
        self.assertFalse(LocationFormerCode.objects.exists())
        self.assertEqual(resolve_location_reference("R301.A"), self.shelf.children.get(short_name="a"))


@override_settings(LANGUAGE_CODE="en")
class FormerCodeAdminTests(CodeTypesMixin, TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser(username="admin"))

    def test_location_page_lists_and_removes_former_codes(self):
        self.rename(self.shelf, "R399")
        page = self.client.get(reverse("admin:inventory_location_change", args=[self.shelf.pk]))
        self.assertContains(page, 'name="former_codes-0-code"')
        self.assertContains(page, "blocked as a former code")
        entry = LocationFormerCode.objects.get(code="R301")
        response = self.client.post(reverse("admin:inventory_locationformercode_delete", args=[entry.pk]), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("R301", [short for _n, _name, short in self.room.free_numbers(self.shelf_type)])

    def test_list_of_former_codes_filters_those_without_location(self):
        LocationFormerCode.objects.create(code="R305", note="old label")
        response = self.client.get(reverse("admin:inventory_locationformercode_changelist"),
                                   {"location__isempty": "1"})
        self.assertContains(response, "R305")


class CompartmentNameTests(CodeTypesMixin, TestCase):
    """Compartments and drawers carry their shelf's or cabinet's name: "Regal 301 Fach c"."""

    def test_new_compartments_are_named_after_their_shelf_or_cabinet(self):
        self.assertEqual(list(self.shelf.children.order_by("short_name").values_list("name", flat=True)),
                         ["Regal 301 Fach a", "Regal 301 Fach b"])
        cabinet = Location.objects.create(type=self.cabinet_type, name="Schrank 300", short_name="S300",
                                          parent_location=self.room)
        self.assertEqual(self.compartment.free_sublocation_names(cabinet, 1), [("Schrank 300 Fach a", "a")])

    def test_a_long_name_falls_back_to_the_plain_one(self):
        self.assertEqual(self.compartment.sublocation_name("x" * 125, "c"), "Fach c")

    def test_renaming_the_shelf_renames_compartments_with_their_default_name(self):
        custom = self.shelf.children.get(short_name="b")
        custom.name = "Ebene B"
        custom.save()
        self.shelf.name = "Regal 301 Leim"
        self.shelf.save()
        self.assertEqual(self.shelf.children.get(short_name="a").name, "Regal 301 Leim Fach a")
        self.assertEqual(self.shelf.children.get(short_name="a").descriptive_identifier,
                         "Halle [HAL] Regal 301 Leim [R301] Regal 301 Leim Fach a [a]")
        self.assertEqual(self.shelf.children.get(short_name="b").name, "Ebene B")
