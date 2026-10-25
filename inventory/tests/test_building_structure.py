
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from accounts.models import Team
from ..models import Location, LocationAxis, LocationType


class StructureTests(TestCase):
    """Inherited details and the levels-and-axes overview of the building structure."""

    @classmethod
    def setUpTestData(cls):
        level = LocationType.objects.create(name="Haus+Ebene", unique=True, structure="level", category="space")
        room = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space")
        part = LocationType.objects.create(name="Teilbereich", structure="area", category="space")
        box = LocationType.objects.create(name="Kiste", unique=True, moveable=True, category="container")
        west, east = LocationAxis.objects.create(number=1, name="West"), LocationAxis.objects.create(number=2, name="Ost")
        wood = Team.objects.create(group=Group.objects.create(name="Werkstattgruppe Holz"), code="H", color="#7d3a2d")
        bio = Team.objects.create(group=Group.objects.create(name="Werkstattgruppe Bio"), code="B", parent=wood)
        hall = Location.objects.create(type=level, name="Werkhaus -1", short_name="WH-1", purpose="Holzwerkstatt",
                                       axis=west)
        hall.responsible_teams.add(wood)
        Location.objects.create(type=level, name="Werkhaus 0", short_name="WH+0")
        cls.changing_room = Location.objects.create(type=room, name="Umkleide", short_name="UMK", parent_location=hall,
                                                    axis=west)
        lab = Location.objects.create(type=room, name="Chemieraum", short_name="CHE", parent_location=hall, axis=east,
                                      fire_load_free=True)
        lab.responsible_teams.add(bio)
        cls.hood = Location.objects.create(type=part, name="Abzug Chemieraum", short_name="1", parent_location=lab,
                                           purpose="Abzug")
        cls.box_hall = Location.objects.create(type=box, name="Kiste 1", short_name="K1", parent_location=hall)
        cls.box_lab = Location.objects.create(type=box, name="Kiste 2", short_name="K2", parent_location=lab)

    def test_inherited_details_stop_at_coded_rooms(self):
        self.assertEqual([t.code for t in self.box_hall.effective_responsible_teams], ["H"])
        self.assertEqual(self.box_hall.purpose_context, "Holzwerkstatt")
        self.assertEqual(self.box_hall.effective_axis.name, "West")
        self.assertEqual(list(self.changing_room.effective_responsible_teams), [])
        self.assertEqual(self.changing_room.purpose_context, "")
        self.assertTrue(self.hood.is_fire_load_free)
        self.assertEqual(self.hood.effective_axis.name, "Ost")
        self.assertEqual([t.code for t in self.hood.effective_responsible_teams], ["B"])
        self.assertEqual(self.hood.purpose_context, "Abzug")
        self.assertTrue(self.box_lab.is_fire_load_free)

    @override_settings(LANGUAGE_CODE="en")
    def test_the_location_page_shows_teams_and_fire_load(self):
        def parts(location):
            page = self.client.get(location.get_absolute_url()).content.decode()
            box = page[page.index('class="location-summary'):page.index("</header>")]
            details = page[page.index('id="location-metadata"'):]
            return box, details[:details.index('class="location-type-details"')]
        box, details = parts(self.box_lab)  # both from the room it is in
        self.assertIn("Werkstattgruppe Bio", box)
        self.assertIn('title="Werkstattgruppe Bio">B</span>', box)
        self.assertEqual(box.count("from Chemieraum"), 1)  # the fire load's; where the teams come from: in the details
        self.assertIn("Free of fire load", box)
        self.assertIn("From Chemieraum · CHE: this location has no teams of its own", details)
        lab, details = parts(Location.objects.get(short_name="CHE"))  # its own
        self.assertIn("Free of fire load", lab)
        self.assertNotIn("from ", lab)
        self.assertIn("Its own teams.", details)
        changing_room, details = parts(self.changing_room)
        self.assertIn("No team yet.", changing_room)
        self.assertNotIn("Free of fire load", changing_room)  # only where it applies
        self.assertIn("No team is responsible for this location", details)

    def test_levels_and_axes_page(self):
        from django.urls import reverse
        page = self.client.get(reverse("structure_overview")).content.decode()
        lab = Location.objects.get(short_name="CHE")
        self.assertIn(f'href="{lab.get_absolute_url()}"', page)
        self.assertIn(f'href="{self.hood.get_absolute_url()}"', page)
        self.assertIn('Abzug <span class="loc-code">.1</span>', page)  # numbered parts relative to their room
        self.assertIn("Werkhaus <span class=\"structure-house-code\">WH</span>", page)  # without the level number
        self.assertIn("--team-bg: #7d3a2d", page)
        self.assertIn("data-print-page", page)  # printing fits the table to the page (structure_overview.css)
        self.assertIn("structure_overview.js", page)
        self.assertNotIn("Kiste 2", page)  # boxes and shelves are left out
        self.assertLess(page.index(">+0<"), page.index(">-1<"))  # upper levels first
        self.assertIn(reverse("structure_overview"), self.client.get(reverse("index_locations")).content.decode())


class TeamBadgeTests(TestCase):
    def test_colour_comes_from_the_parent_and_text_follows_contrast(self):
        wood = Team.objects.create(group=Group.objects.create(name="Holz"), code="H", color="#7d3a2d")
        bio = Team.objects.create(group=Group.objects.create(name="Bio"), code="B", parent=wood)
        textile = Team.objects.create(group=Group.objects.create(name="Textil"), code="T", color="#f3e634")
        plain = Team.objects.create(group=Group.objects.create(name="Ohne"))
        self.assertEqual((bio.badge_color, bio.badge_text_color), ("#7d3a2d", "#ffffff"))
        self.assertEqual(textile.badge_text_color, "#000000")
        self.assertEqual((plain.badge_color, plain.badge_text_color), ("", ""))


class AdminOnlyTypeTests(TestCase):
    """Admin-only location types are created, changed and deleted only in the admin."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        cls.structure = LocationType.objects.create(name="Raum", unique=True, admin_only=True)
        cls.box = LocationType.objects.create(name="Kiste", unique=True, moveable=True)
        cls.room = Location.objects.create(type=cls.structure, name="Chemieraum", short_name="CHE")
        cls.crate = Location.objects.create(type=cls.box, name="Kiste", short_name="K1", parent_location=cls.room)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            codename__in=["change_location", "delete_location"], content_type__app_label="inventory"))

    def setUp(self):
        self.client.force_login(self.member)

    def test_type_cannot_be_admin_only_and_changeable_on_the_pages(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            LocationType(name="Halb", admin_only=True, moveable=True).full_clean()

    def test_the_building_structure_is_changed_in_the_admin_only(self):
        from django.urls import reverse
        # Also the purpose: it is locked like the description and photo.
        self.assertEqual(self.client.post(reverse("location_purpose_update", args=[self.room.pk]),
                                          {"purpose": "Labor"}).status_code, 403)
        self.assertEqual(Location.objects.get(pk=self.room.pk).purpose, "")
        self.assertEqual(self.client.post(reverse("location_overview_update", args=[self.room.pk])).status_code, 403)
        page = self.client.get(self.room.get_absolute_url(), HTTP_ACCEPT_LANGUAGE="en").content.decode()
        self.assertNotIn('id="location-purpose-editor"', page)
        self.assertNotIn('id="location-overview-editor"', page)
        self.assertNotIn("Edit purpose", page)  # what cannot be changed has no pencil
        Location.objects.filter(pk=self.room.pk).update(purpose="Labor")
        page = self.client.get(self.room.get_absolute_url(), HTTP_ACCEPT_LANGUAGE="en").content.decode()
        self.assertNotIn("Edit purpose", page)  # also with a purpose
        self.assertIn("Labor", page)
        crate_page = self.client.get(self.crate.get_absolute_url()).content.decode()
        self.assertIn('id="location-overview-editor"', crate_page)

    def test_deleting_is_left_to_the_admin(self):
        from ..permissions import can_delete_location
        self.assertFalse(can_delete_location(self.member, self.room))


class NumberRangeTests(TestCase):
    """Area-numbered types get free numbers from the ranges of their room or area."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from ..models import LocationNumberRange
        room = LocationType.objects.create(name="Raum", unique=True, structure="room", admin_only=True)
        part = LocationType.objects.create(name="Teilbereich", structure="area")
        naming = {"unique": True, "area_numbering": True, "auto_short_name_padding_length": 3, "auto_sequence": "0123456789"}
        cls.shelf = LocationType.objects.create(name="Regal", auto_name_prefix="Regal", auto_short_name_prefix="R", **naming)
        cls.cabinet = LocationType.objects.create(name="Schrank", auto_name_prefix="Schrank", auto_short_name_prefix="S", **naming)
        cls.hall = Location.objects.create(type=room, name="Halle", short_name="HAL")
        cls.stage = Location.objects.create(type=part, name="Bühne", short_name="1", parent_location=cls.hall)
        cls.wc = Location.objects.create(type=room, name="WC", short_name="WC1", parent_location=cls.hall)
        LocationNumberRange.objects.create(location=cls.hall, type=cls.shelf, first=300, last=303)
        LocationNumberRange.objects.create(location=cls.hall, type=cls.cabinet, first=300, last=301)
        Location.objects.create(type=cls.shelf, name="Regal 300", short_name="R300", parent_location=cls.hall)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(Permission.objects.get(codename="add_location"))

    def test_free_numbers_per_type_from_the_range_above(self):
        self.assertEqual([short for _n, _name, short in self.stage.free_numbers(self.shelf)], ["R301", "R302", "R303"])
        self.assertEqual([short for _n, _name, short in self.stage.free_numbers(self.cabinet)], ["S300", "S301"])
        # A range applies to everything below, also to rooms with their own code.
        self.assertEqual([short for _n, _name, short in self.wc.free_numbers(self.shelf)], ["R301", "R302", "R303"])
        self.assertEqual([kind.name for kind, _source in self.stage.numbering_types()], ["Regal", "Schrank"])

    def test_a_part_can_reserve_numbers_that_its_neighbours_do_not_get(self):
        from ..models import LocationNumberRange
        LocationNumberRange.objects.create(location=self.stage, type=self.shelf, first=302, last=303)
        self.assertEqual([s for _n, _name, s in self.stage.free_numbers(self.shelf)], ["R302", "R303"])
        self.assertEqual([s for _n, _name, s in self.wc.free_numbers(self.shelf)], ["R301"])
        self.assertEqual([s for _n, _name, s in self.hall.free_numbers(self.shelf)], ["R301"])
        # Reserving within the range above is fine; reaching beyond it or into a neighbour's reservation is not.
        self.assertIsNone(LocationNumberRange.overlap_error(301, 301, self.shelf, self.wc))
        self.assertIsNotNone(LocationNumberRange.overlap_error(302, 302, self.shelf, self.wc))
        self.assertIsNotNone(LocationNumberRange.overlap_error(303, 310, self.shelf, self.wc))

    def test_ranges_of_one_type_must_not_overlap(self):
        from ..models import LocationNumberRange
        other = Location.objects.create(type=self.hall.type, name="Lager", short_name="LAG1")
        self.assertIsNotNone(LocationNumberRange.overlap_error(303, 310, self.shelf, other))
        self.assertIsNone(LocationNumberRange.overlap_error(302, 310, self.cabinet, other))

    def test_new_ranges_go_into_the_middle_of_the_largest_gap(self):
        from ..models import LocationNumberRange
        # Taken for shelves: 300–303 (range) and R300; free: 0–299 and 304–999 with R998 used in between.
        Location.objects.create(type=self.shelf, name="Regal 998", short_name="R998", parent_location=self.hall)
        self.assertEqual(LocationNumberRange.suggest(self.shelf), (640, 659))
        self.assertEqual(LocationNumberRange.suggest(self.shelf, size=1000), None)
        # Below a location with a range, the suggestion is a reservation within it.
        self.assertEqual(LocationNumberRange.suggest(self.shelf, self.stage, size=2), (301, 302))

    def test_type_needs_global_codes_and_digits(self):
        from django.core.exceptions import ValidationError
        for flags in ({"unique": False}, {"auto_sequence": "abcdefghijklmnopqrstuvwxyz"}, {"auto_short_name_prefix": ""}):
            with self.subTest(flags=flags), self.assertRaises(ValidationError):
                LocationType(**{"name": "X", "unique": True, "area_numbering": True, "auto_short_name_prefix": "X",
                                "auto_sequence": "0123456789", **flags}).full_clean()
        # Shelves and cabinets may be moved (e.g. onto a pallet); they keep their number.
        LocationType(name="X", unique=True, area_numbering=True, moveable=True, auto_short_name_prefix="X",
                     auto_sequence="0123456789").full_clean()

    def page(self, location, kind=None):
        from django.urls import reverse
        url = reverse("numbered_location_create", args=[location.pk])
        return url + (f"?type={kind.pk}" if kind else "")

    def test_first_step_asks_what_is_added(self):
        self.client.force_login(self.member)
        page = self.client.get(self.page(self.stage)).content.decode()
        self.assertIn(f"?type={self.shelf.pk}", page)
        self.assertIn(f"?type={self.cabinet.pk}", page)
        detail = self.client.get(self.stage.get_absolute_url()).content.decode()
        self.assertIn(self.page(self.stage), detail)
        self.assertIn("Regal / Schrank", detail)

    def test_reserved_number_comes_first_and_neighbour_hint_is_shown(self):
        self.client.force_login(self.member)
        page = self.client.get(self.page(self.stage, self.shelf)).content.decode()
        self.assertRegex(page, r'<select name="reserved"[^>]*>\s*<option value="301"')
        self.assertNotIn('value="300"', page)
        self.assertIn("links", page)
        response = self.client.post(self.page(self.stage), {"type": self.shelf.pk, "mode": "reserved", "reserved": "302",
                                                              "purpose": "Farben"})
        created = Location.objects.get(short_name="R302")
        self.assertRedirects(response, created.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((created.name, created.parent_location, created.purpose), ("Regal 302", self.stage, "Farben"))
        retry = self.client.post(self.page(self.stage), {"type": self.shelf.pk, "mode": "reserved", "reserved": "302"})
        self.assertEqual(retry.status_code, 200)
        shelf_page = self.client.get(created.get_absolute_url()).content.decode()
        self.assertNotIn(self.page(created), shelf_page)

    def test_wished_for_number_reserves_the_following_ones(self):
        from ..models import LocationNumberRange
        self.client.force_login(self.member)
        store = Location.objects.create(type=self.hall.type, name="Lager", short_name="LAG1")
        taken = self.client.post(self.page(store), {"type": self.shelf.pk, "mode": "wish", "wish": 302, "expected": 1})
        self.assertContains(taken, "302", status_code=200)  # reserved for the hall
        short = self.client.post(self.page(store), {"type": self.shelf.pk, "mode": "wish", "wish": 298, "expected": 5})
        self.assertContains(short, "298", status_code=200)  # only 298 and 299 are free before 300
        self.client.post(self.page(store), {"type": self.shelf.pk, "mode": "wish", "wish": 500, "expected": 4})
        self.assertEqual(Location.objects.get(short_name="R500").parent_location, store)
        number_range = LocationNumberRange.objects.get(location=store)
        self.assertEqual((number_range.type, number_range.first, number_range.last), (self.shelf, 500, 503))

    def test_new_number_reserves_the_expected_ones_and_adds_compartments(self):
        from ..models import LocationNumberRange
        compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach", auto_sequence="abcdefghijklmnopqrstuvwxyz")
        self.shelf.sublocation_type = compartment
        self.shelf.save()
        self.client.force_login(self.member)
        store = Location.objects.create(type=self.hall.type, name="Lager", short_name="LAG1")
        page = self.client.get(self.page(store, self.shelf)).content.decode()
        self.assertNotIn('name="reserved"', page)
        self.assertIn('name="sublocations"', page)
        self.client.post(self.page(store), {"type": self.shelf.pk, "mode": "auto", "expected": 5, "sublocations": 3})
        number_range = LocationNumberRange.objects.get(location=store)
        self.assertEqual(number_range.last - number_range.first + 1, 5)
        first = Location.objects.get(parent_location=store)
        self.assertEqual(first.short_name, f"R{number_range.first:03d}")
        # Compartments carry their shelf's name: "Regal 640 Fach a".
        self.assertEqual(list(first.children.order_by("short_name").values_list("name", "short_name")),
                         [(f"{first.name} Fach {code}", code) for code in "abc"])

    def test_a_used_up_range_grows_right_behind_it(self):
        from ..models import LocationNumberRange
        self.client.force_login(self.member)
        for number in (301, 302, 303):
            Location.objects.create(type=self.shelf, name=f"Regal {number}", short_name=f"R{number}", parent_location=self.hall)
        self.client.post(self.page(self.stage), {"type": self.shelf.pk, "mode": "auto", "expected": 3})
        hall_range = LocationNumberRange.objects.get(location=self.hall, type=self.shelf)
        self.assertEqual((hall_range.first, hall_range.last), (300, 306))
        self.assertEqual(Location.objects.get(short_name="R304").parent_location, self.stage)

    def test_more_compartments_get_the_next_free_letters(self):
        from django.urls import reverse
        compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach", auto_sequence="abcdefghijklmnopqrstuvwxyz")
        self.shelf.sublocation_type = compartment
        self.shelf.save()
        shelf = Location.objects.get(short_name="R300")
        for char in "ac":
            Location.objects.create(type=compartment, name=f"Fach {char}", short_name=char, parent_location=shelf)
        self.client.force_login(self.member)
        url = reverse("sublocation_add", args=[shelf.pk])
        self.assertIn(url, self.client.get(shelf.get_absolute_url()).content.decode())
        self.assertRedirects(self.client.post(url, {"count": 3}), shelf.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(sorted(shelf.children.values_list("short_name", flat=True)), ["a", "b", "c", "d", "e"])
        self.assertEqual(shelf.children.get(short_name="b").name, "Regal 300 Fach b")
        self.assertEqual(self.client.post(url, {"count": 101}).status_code, 200)  # at most 100 at a time
        self.client.post(url, {"count": 23})
        codes = set(shelf.children.values_list("short_name", flat=True))
        self.assertTrue({"x", "y", "z", "aa", "ab"} <= codes and "ac" not in codes)
        self.assertEqual(self.client.get(reverse("sublocation_add", args=[self.hall.pk])).status_code, 404)

    def test_only_the_fields_of_the_chosen_way_count(self):
        self.client.force_login(self.member)
        page = self.client.get(self.page(self.stage, self.shelf)).content.decode()
        self.assertIn('<span class="input-group-text">R</span><input type="number" name="wish"', page)
        self.assertIn("numbered_location.js", page)
        response = self.client.post(self.page(self.stage), {"type": self.shelf.pk, "mode": "reserved", "reserved": "301",
                                                              "wish": "abc", "expected": 0})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Location.objects.filter(short_name="R301").exists())

    def test_purposes_of_new_compartments_can_be_given_right_away(self):
        from django.urls import reverse
        compartment = LocationType.objects.create(name="Fach/Schub", auto_name_prefix="Fach", auto_sequence="abcdefghijklmnopqrstuvwxyz")
        self.shelf.sublocation_type = compartment
        self.shelf.save()
        from django.contrib.auth.models import Permission
        self.member.user_permissions.add(Permission.objects.get(codename="change_location"))
        self.client.force_login(self.member)
        response = self.client.post(self.page(self.stage), {"type": self.shelf.pk, "mode": "reserved", "reserved": "301",
                                                              "sublocations": 2})
        shelf = Location.objects.get(short_name="R301")
        purposes = reverse("sublocation_purposes", args=[shelf.pk]) + "?codes=a,b"
        self.assertRedirects(response, purposes, fetch_redirect_response=False)
        page = self.client.get(purposes).content.decode()
        fields = {part.short_name: f"purpose_{part.pk}" for part in shelf.children.all()}
        self.assertLess(page.index(fields["b"]), page.index(fields["a"]), "listed top down, a at the bottom")
        self.assertIn("R301.a</text>", page)
        self.assertNotIn("R302</text>", page)
        self.assertRedirects(self.client.post(purposes, {"codes": "a,b", fields["a"]: "Schrauben M4", fields["b"]: ""}),
                             shelf.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(shelf.children.get(short_name="a").purpose, "Schrauben M4")
        self.assertEqual(shelf.children.get(short_name="a").history.count(), 1)

    def test_creating_needs_the_add_permission(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        self.client.force_login(get_user_model().objects.create_user(username="guest"))
        self.assertEqual(self.client.get(reverse("numbered_location_create", args=[self.stage.pk])).status_code, 403)


class MassAddTests(TestCase):
    """Generated codes skip taken ones, e.g. older hexadecimal box codes that look decimal."""

    def test_free_names_skip_taken_codes(self):
        box = LocationType.objects.create(name="Kiste", unique=True, moveable=True, auto_name_prefix="Kiste",
                                          auto_short_name_prefix="K", auto_short_name_padding_length=4,
                                          auto_sequence="0123456789")
        Location.objects.create(type=box, name="Kiste 0100", short_name="K0100")
        Location.objects.create(type=box, name="Kiste 034c", short_name="K034c")
        self.assertEqual([short for _name, short in box.free_names(3, "99")], ["K0099", "K0101", "K0102"])
        self.assertTrue(box.is_valid_start("0525"))
        self.assertFalse(box.is_valid_start("034c"))
