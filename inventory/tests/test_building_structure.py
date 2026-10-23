import copy
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import Team
from ..building_structure import validate_dataset
from ..models import Item, ItemLocation, Location, LocationType, MeasurementUnit

DATASET = {
    "types": {
        "level": {"name": "Haus+Ebene", "unique": True, "structure": "level"},
        "room": {"name": "Raum", "unique": True, "structure": "room", "deletable_in_frontend": True,
                 "description": "Raum mit Wänden und Tür"},
        "subarea": {"name": "Teilbereich", "unique": False, "structure": "area"},
        "mobile": {"name": "Mobil", "unique": True, "admin_only": True},
        "shelf": {"name": "Regal", "unique": True, "area_numbering": True, "auto_name_prefix": "Regal",
                  "auto_short_name_prefix": "R", "auto_short_name_padding_length": 3, "auto_sequence": "0123456789"},
    },
    "teams": [
        {"code": "H", "group": "Werkstattgruppe Holz", "color": "#7d3a2d"},
        {"code": "B", "group": "Werkstattgruppe Bio", "parent": "H"},
    ],
    "axes": [{"number": 1, "name": "West"}, {"number": 2, "name": "Ost"}],
    "replaces_types": ["Haus+Etage", "Raum/Bereich"],
    "retire_types": ["Raum/Bereich", "Haus+Etage"],
    "locations": [
        {"path": "WH-1", "type": "level", "name": "Werkhaus -1", "old": "N0", "purpose": "Holzwerkstatt",
         "teams": ["H"], "axis": 1},
        {"path": "WH+0", "type": "level", "name": "Werkhaus 0", "old": "N1"},
        {"path": "WH-1.UMK", "type": "room", "name": "Umkleide", "axis": 1,
         "number_ranges": [{"type": "shelf", "from": 300, "to": 302}]},
        {"path": "WH+0.CHE", "type": "room", "name": "Chemieraum", "old": "N1.CL", "axis": 2,
         "fire_load_free": True, "teams": ["B"]},
        {"path": "WH+0.CHE.1", "type": "subarea", "name": "Abzug Chemieraum", "purpose": "Abzug"},
        {"path": "WH+0.AUS1", "type": "room", "name": "Außenbereich", "axis": 2, "outdoor": True},
        {"path": "mobil", "type": "mobile", "name": "Mobil", "old": "mobil"},
    ],
    "remove": [{"old": "N1.1", "permanent": True}, {"old": "N1.X", "move_to": "WH+0"}],
}


class BuildingStructureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        floor = LocationType.objects.create(name="Haus+Etage", unique=True)
        room = LocationType.objects.create(name="Raum/Bereich", unique=False)
        box = LocationType.objects.create(name="Kiste", unique=True, moveable=True)
        cls.n0 = Location.objects.create(type=floor, name="Nord UG", short_name="N0", physical_description="alt")
        cls.n1 = Location.objects.create(type=floor, name="EG Nord", short_name="N1")
        Location.objects.create(type=floor, name="Mobil", short_name="mobil")
        Location.objects.create(type=room, name="Alt", short_name="Z", parent_location=cls.n1).delete()
        cls.lab = Location.objects.create(type=room, name="Chemielabor", short_name="CL", parent_location=cls.n1)
        Location.objects.create(type=room, name="Büro", short_name="1", parent_location=cls.n1)
        cls.store = Location.objects.create(type=room, name="Lager", short_name="X", parent_location=cls.n1)
        cls.box_hall = Location.objects.create(type=box, name="Kiste 1", short_name="K1", parent_location=cls.n0)
        cls.box_lab = Location.objects.create(type=box, name="Kiste 2", short_name="K2", parent_location=cls.lab)
        cls.box_store = Location.objects.create(type=box, name="Kiste 3", short_name="K3", parent_location=cls.store)
        Team.objects.create(group=Group.objects.create(name="Werkstattgruppe Holz"))
        unit = MeasurementUnit.objects.create(name="Stück", short="Stk")
        cls.stock = ItemLocation.objects.create(item=Item.objects.create(name="Lampe", measurement_unit=unit),
                                                location=cls.store, amount=3)

    def run_command(self, data=DATASET, *args):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structure.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            out = StringIO()
            call_command("building_restructure", str(path), *args, stdout=out)
            return out.getvalue()

    def test_validation_finds_order_duplicates_and_unknown_references(self):
        data = copy.deepcopy(DATASET)
        data["locations"].insert(0, {"path": "WH+0.ZZ", "type": "room", "name": "Zu früh"})
        data["locations"].append({"path": "WH-1.CHE", "type": "room", "name": "Doppelt", "teams": ["Q"]})
        data["types"]["room"]["moveable"] = "ja"
        errors = "\n".join(validate_dataset(data))
        self.assertIn("parent WH+0 must be listed before it", errors)
        self.assertIn("code CHE is already used by WH+0.CHE", errors)
        self.assertIn("unknown team Q", errors)
        self.assertIn("type room: moveable must be true or false", errors)
        data["locations"][1]["number_ranges"] = [{"type": "shelf", "from": 300, "to": 310}]
        next(e for e in data["locations"] if e["path"] == "WH-1.UMK")["number_ranges"].append(
            {"type": "shelf", "from": 400, "to": 410})
        next(e for e in data["locations"] if e["path"] == "WH+0")["number_ranges"] = [
            {"type": "shelf", "from": 405, "to": 420}]
        next(e for e in data["locations"] if e["path"] == "WH-1.UMK")["number_ranges"].append(
            {"type": "room", "from": 0, "to": 9})
        errors = "\n".join(validate_dataset(data))
        self.assertNotIn("number range 300–302 overlaps", errors)  # WH-1.UMK reserves within WH-1
        self.assertIn("number range 400–410 overlaps WH+0", errors)
        self.assertIn("number range 0–9 needs a type with area_numbering", errors)

    def test_dry_run_changes_nothing(self):
        output = self.run_command()
        self.assertIn("Dry run (4 moved, 3 created, 0 already in place, 2 removed, 2 types retired, 0 containers moved in)", output)
        self.assertIn("retire Raum/Bereich: type and its 3 deleted locations are deleted permanently", output)
        self.assertIn("remove N1.1         Büro (permanently)", output)
        self.assertIn("description 'alt' is replaced by ''", output)
        self.assertEqual(Location.objects.get(pk=self.lab.pk).locatable_identifier, "N1.CL")
        self.assertFalse(LocationType.objects.filter(name="Raum").exists())

    def test_apply_moves_in_place_creates_and_removes(self):
        self.run_command(DATASET, "--apply")
        lab = Location.objects.get(pk=self.lab.pk)
        self.assertEqual((lab.locatable_identifier, lab.unique_identifier, lab.type.name), ("WH+0.CHE", "CHE", "Raum"))
        self.assertEqual((lab.type.deletable_in_frontend, lab.type.moveable, lab.type.structure), (True, False, "room"))
        self.assertEqual(lab.type.description, "Raum mit Wänden und Tür")
        self.assertEqual(Location.objects.get(pk=self.box_lab.pk).locatable_identifier, "WH+0.CHE.K2")
        self.assertEqual(Location.objects.get(pk=self.n0.pk).purpose, "Holzwerkstatt")
        part = Location.objects.get(locatable_identifier="WH+0.CHE.1")
        self.assertEqual(part.unique_identifier, "CHE.1")
        self.assertTrue(Location.objects.get(locatable_identifier="WH+0.AUS1").outdoor)
        self.assertFalse(Location.objects.filter(locatable_identifier="WH+0.1").exists())
        self.assertFalse(Location.objects.filter(pk=self.store.pk).exists())  # deleted with its retired type
        self.assertEqual(Location.objects.get(pk=self.box_store.pk).parent_location_id, self.n1.pk)
        self.assertEqual(ItemLocation.objects.get(pk=self.stock.pk).location_id, self.n1.pk)
        holz, bio = Team.objects.get(code="H"), Team.objects.get(code="B")
        self.assertEqual((holz.color, bio.parent), ("#7d3a2d", holz))
        self.assertEqual(list(lab.responsible_teams.all()), [bio])

        again = self.run_command(DATASET, "--apply")
        self.assertIn("0 moved, 0 created, 7 already in place, 0 removed, 0 types retired, 0 containers moved in", again)
        self.assertFalse(LocationType.objects.filter(name__in=["Haus+Etage", "Raum/Bereich"]).exists())
        self.assertFalse(Location.objects.filter(short_name="Z").exists())
        self.assertEqual(Location.objects.get(short_name="mobil").type.name, "Mobil")

    def test_renamed_locations_are_found_by_their_former_path_and_containers_move_in(self):
        self.run_command(DATASET, "--apply")
        changing_room = Location.objects.get(locatable_identifier="WH-1.UMK")
        data = copy.deepcopy(DATASET)
        entry = next(e for e in data["locations"] if e["path"] == "WH-1.UMK")
        entry["path"] = "WH-1.UMZ"
        with self.assertRaisesMessage(CommandError, "WH-1.UMK (Umkleide) is not in the dataset"):
            self.run_command(data)
        entry["was"] = ["WH-1.UMK"]
        data["moves"] = [{"codes": ["K1"], "to": "WH-1.UMZ"}]
        output = self.run_command(data, "--apply")
        self.assertIn("move   WH-1.UMK   → WH-1.UMZ", output)
        self.assertIn("1 moved", output)
        self.assertIn("1 containers moved in", output)
        self.assertEqual(Location.objects.get(pk=changing_room.pk).locatable_identifier, "WH-1.UMZ")
        self.assertEqual(Location.objects.get(pk=self.box_hall.pk).locatable_identifier, "WH-1.UMZ.K1")
        self.assertIn("done   K1", self.run_command(data))

    def test_axes_missing_from_the_dataset_are_deleted(self):
        from ..models import LocationAxis
        self.run_command(DATASET, "--apply")
        data = copy.deepcopy(DATASET)
        data["axes"] = [{"number": 1, "name": "West"}]
        for entry in data["locations"]:
            if entry.get("axis") == 2:
                entry["axis"] = 1
        self.run_command(data, "--apply")
        self.assertEqual(list(LocationAxis.objects.values_list("number", flat=True)), [1])
        self.assertEqual(Location.objects.get(pk=self.lab.pk).axis.number, 1)

    def test_every_replaced_location_needs_a_successor(self):
        data = copy.deepcopy(DATASET)
        data["remove"] = data["remove"][1:]
        with self.assertRaisesMessage(CommandError, "N1.1 (Büro) is neither moved, removed nor kept"):
            self.run_command(data, "--apply")
        self.assertEqual(Location.objects.get(pk=self.lab.pk).locatable_identifier, "N1.CL")

    def test_removing_a_location_with_contents_needs_a_target(self):
        data = copy.deepcopy(DATASET)
        del data["remove"][1]["move_to"]
        with self.assertRaisesMessage(CommandError, "remove N1.X: it still holds 1 locations and 1 stock entries and has no move_to"):
            self.run_command(data)

    def test_inherited_details_stop_at_coded_rooms(self):
        self.run_command(DATASET, "--apply")
        box_hall = Location.objects.get(pk=self.box_hall.pk)
        self.assertEqual([t.code for t in box_hall.effective_responsible_teams], ["H"])
        self.assertEqual(box_hall.purpose_context, "Holzwerkstatt")
        self.assertEqual(box_hall.effective_axis.name, "West")
        changing_room = Location.objects.get(locatable_identifier="WH-1.UMK")
        self.assertEqual(list(changing_room.effective_responsible_teams), [])
        self.assertEqual(changing_room.purpose_context, "")
        part = Location.objects.get(locatable_identifier="WH+0.CHE.1")
        self.assertTrue(part.is_fire_load_free)
        self.assertEqual(part.effective_axis.name, "Ost")
        self.assertEqual([t.code for t in part.effective_responsible_teams], ["B"])
        self.assertEqual(part.purpose_context, "Abzug")
        self.assertTrue(Location.objects.get(pk=self.box_lab.pk).is_fire_load_free)

    def test_overview_from_database_and_dataset(self):
        self.run_command(DATASET, "--apply")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "overview.html"
            call_command("building_overview", "-o", str(target), stdout=StringIO())
            html = target.read_text(encoding="utf-8")
            self.assertIn('"c": "CHE"', html)
            self.assertIn('"c": "1"', html)
            self.assertNotIn("K2", html)  # boxes and shelves are left out
            source = Path(tmp) / "structure.json"
            source.write_text(json.dumps(DATASET), encoding="utf-8")
            call_command("building_overview", "--dataset", str(source), "-o", str(target), stdout=StringIO())
            self.assertIn('"o": "N1.CL"', target.read_text(encoding="utf-8"))


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

    def test_only_the_purpose_stays_editable(self):
        from django.urls import reverse
        self.assertEqual(self.client.post(reverse("location_purpose_update", args=[self.room.pk]),
                                          {"purpose": "Labor"}).status_code, 302)
        self.assertEqual(Location.objects.get(pk=self.room.pk).purpose, "Labor")
        self.assertEqual(self.client.post(reverse("location_overview_update", args=[self.room.pk])).status_code, 403)
        page = self.client.get(self.room.get_absolute_url(), HTTP_ACCEPT_LANGUAGE="en").content.decode()
        self.assertIn("can only be changed in the admin, except for their purpose", page)
        self.assertIn('id="location-purpose-editor"', page)
        self.assertNotIn('id="location-overview-editor"', page)
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

    def test_type_needs_fixed_global_codes_and_digits(self):
        from django.core.exceptions import ValidationError
        for flags in ({"moveable": True}, {"unique": False}, {"auto_sequence": "abcdefghijklmnopqrstuvwxyz"}):
            with self.subTest(flags=flags), self.assertRaises(ValidationError):
                LocationType(**{"name": "X", "unique": True, "area_numbering": True, "auto_short_name_prefix": "X",
                                "auto_sequence": "0123456789", **flags}).full_clean()

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
        self.assertEqual(list(first.children.order_by("short_name").values_list("name", "short_name")),
                         [("Fach a", "a"), ("Fach b", "b"), ("Fach c", "c")])

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
        self.assertEqual(shelf.children.get(short_name="b").name, "Fach b")
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
