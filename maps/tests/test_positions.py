from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import ChangeLog, Item, Location, LocationType, MeasurementUnit, UniqueItem

from .. import geo, positions
from ..levels import Tree, effective_shape
from ..models import LocationShape, LocationTypeMap, UniqueItemPosition
from .test_geo import CENTER, local_point


class Building:
    """WH-1 › HBB (stacked: HBB.1 below, HBB.2 above) › pallet P1 › box K1 with a saw; a room LAG next to it."""

    @classmethod
    def build(cls):
        level = LocationType.objects.create(name="Haus+Ebene", unique=True, structure="level", category="space",
                                            admin_only=True)
        area = LocationType.objects.create(name="Bereich", unique=True, structure="area", category="space",
                                           admin_only=True)
        part = LocationType.objects.create(name="Teilbereich", structure="area", category="space", admin_only=True)
        cls.pallet_type = LocationType.objects.create(name="Palette", unique=True, moveable=True, category="container")
        box = LocationType.objects.create(name="Kiste", unique=True, moveable=True, category="container",
                                          no_sublocations=True)
        # Containers are not placed, as in the admin's settings for now; PositionTests places them.
        LocationTypeMap.objects.create(type=cls.pallet_type, placeable=False, default_width_cm=120, default_depth_cm=80)
        cls.box_type = box
        cls.level = Location.objects.create(type=level, name="Werkhaus -1", short_name="WH-1")
        cls.other_level = Location.objects.create(type=level, name="Haupthaus -1", short_name="HH-1")
        cls.hbb = Location.objects.create(type=area, name="Holzbaubühne", short_name="HBB", parent_location=cls.level)
        cls.lower = Location.objects.create(type=part, name="unten", short_name="1", parent_location=cls.hbb)
        cls.upper = Location.objects.create(type=part, name="oben", short_name="2", parent_location=cls.hbb)
        cls.store = Location.objects.create(type=area, name="Lager", short_name="LAG", parent_location=cls.level)
        cls.pallet = Location.objects.create(type=cls.pallet_type, name="Palette 1", short_name="P1",
                                             parent_location=cls.upper)
        cls.box = Location.objects.create(type=box, name="Kiste 1", short_name="K1", parent_location=cls.pallet)
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.saw = UniqueItem.objects.create(
            item=Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, measurement_unit=unit), location=cls.box)
        LocationShape.objects.create(location=cls.hbb, parts_stacked=True)


class LevelTests(Building, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def test_level_and_stacked_part_come_from_the_tree(self):
        tree = Tree()
        self.assertEqual(tree.level(self.box.pk), self.level.pk)
        self.assertEqual(tree.level_number(self.box.pk), -1)
        self.assertEqual(tree.stack(self.box.pk), (self.hbb.pk, self.upper.pk))
        self.assertIsNone(tree.stack(self.store.pk))
        self.assertEqual(tree.levels(), {-1: [self.other_level.pk, self.level.pk]})  # HH before WH
        self.assertEqual(sorted(tree.descendants(self.pallet.pk)), [self.box.pk])

    def test_the_tree_loads_what_is_asked_for(self):
        # A few locations: one recursive query; many (or a queryset): one query per step up. Both give the same.
        few = Tree()
        self.assertEqual((few.level(self.box.pk), few.depth(self.box.pk)), (self.level.pk, 5))  # K1, P1, HBB.2, HBB, WH-1
        self.assertNotIn(self.other_level.pk, few.nodes)  # only what was asked for, and what is above it
        many = Tree()
        many.FEW = 0
        many.load(Location.objects.filter(pk__in=[self.box.pk, self.store.pk]).values("pk"))
        self.assertEqual({pk: many.nodes[pk] for pk in few.nodes}, few.nodes)
        self.assertEqual(many.on_level([self.box.pk, self.store.pk, self.other_level.pk], -1),
                         [self.box.pk, self.store.pk, self.other_level.pk])
        self.assertEqual(sorted(many.descendants(self.pallet.pk)), [self.box.pk])
        Location.objects.filter(pk=self.box.pk).update(is_deleted=True)  # deleted: not in the tree, nor below its parent
        self.assertIsNone(Tree().level(self.box.pk))
        self.assertEqual(Tree().descendants(self.pallet.pk), [])

    def test_without_a_position_of_its_own_the_nearest_one_above_counts(self):
        self.assertIsNone(effective_shape(self.box))
        positions.set_location_shape(self.pallet, None, CENTER)
        shape, source, exact = effective_shape(self.box)
        self.assertEqual((source, exact), (self.pallet, False))


class TypeLookTests(Building, TestCase):
    """maps 0004: the standard look of the types, without undoing what was changed in the admin."""

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def test_the_standard_look_keeps_changes_made_in_the_admin(self):
        from django.apps import apps
        from importlib import import_module
        area = LocationType.objects.get(name="Bereich")
        # As maps 0002 set it, then a fill opacity of 0 chosen in the admin.
        LocationTypeMap.objects.create(type=area, as_point=False, as_rectangle=False, as_area=True, color="#b45309",
                                       fill_color="#fcd34d", fill_opacity=0, line_width=2,
                                       style_options={"dashArray": "8 5"}, label_min_zoom=18)
        import_module("maps.migrations.0004_type_looks_true_north").type_looks(apps, None)
        settings = LocationTypeMap.objects.get(type=area)
        self.assertEqual(settings.style(), {"dashArray": "8 4", "color": "#d97706", "fillColor": "#fde68a",
                                            "fillOpacity": 0, "weight": 2})
        self.assertTrue(settings.label_bold)
        level = LocationTypeMap.objects.get(type__name="Haus+Ebene")  # had none: made, placed as areas
        self.assertEqual((level.placeable, level.kinds(), level.color), (True, ["area"], "#334155"))
        pallet = LocationTypeMap.objects.get(type=self.pallet_type)  # no look of its own: stays as it was
        self.assertEqual((pallet.placeable, pallet.default_width_cm, pallet.style()), (False, 120, {}))
        self.assertEqual(LocationTypeMap.objects.get(type__name="Kiste").default_width_cm, 60)


# The mechanics with a pallet and a unique item; installations choose what is placed (admin: location types).
@override_settings(LANGUAGE_CODE="en", MAPS_PLACE_UNIQUE_ITEMS=True)
class PositionTests(Building, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()
        LocationTypeMap.objects.filter(type=cls.pallet_type).update(placeable=True)
        LocationTypeMap.objects.create(type=cls.box_type, placeable=True)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["change_location", "change_uniqueitem"]))

    def place_all(self):
        positions.set_location_shape(self.pallet, None, CENTER)
        positions.set_location_shape(self.box, None, local_point(0.3, 0))
        positions.set_item_position(self.saw, local_point(0.3, 0.1))

    def shape(self, location):
        return LocationShape.objects.filter(location=location).first()

    def test_a_pallet_becomes_a_rectangle_of_its_size(self):
        shape = positions.set_location_shape(self.pallet, None, CENTER, 30)
        self.assertEqual((shape.kind, shape.rotation), (LocationShape.Kind.RECTANGLE, 30))
        self.assertAlmostEqual(geo.area_m2(shape.geometry), 0.96, places=3)
        self.assertLess(geo.distance_m(geo.anchor(shape.geometry), CENTER), 0.001)
        box = positions.set_location_shape(self.box, None, local_point(0.3, 0))
        self.assertEqual(box.kind, LocationShape.Kind.POINT)  # no size known

    def test_what_is_on_it_moves_along(self):
        self.place_all()
        positions.set_location_shape(self.pallet, None, local_point(10, 0), 90)
        box, saw = self.shape(self.box).geometry, UniqueItemPosition.objects.get().point
        here = geo.local(local_point(10, 0))
        self.assertAlmostEqual(geo.local(box).x - here.x, 0, places=3)
        self.assertAlmostEqual(geo.local(box).y - here.y, -0.3, places=3)  # east turned to south
        self.assertAlmostEqual(geo.local(saw).x - here.x, 0.1, places=3)
        self.assertAlmostEqual(geo.local(saw).y - here.y, -0.3, places=3)

    def test_another_parent_without_a_position_clears_it_and_what_is_on_it(self):
        self.place_all()
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 5, 5))
        self.pallet.parent_location = self.store
        self.pallet.save()
        self.assertIsNone(self.shape(self.pallet).geometry)
        self.assertIsNone(self.shape(self.box).geometry)
        self.assertFalse(UniqueItemPosition.objects.exists())
        self.assertIsNotNone(self.shape(self.store).geometry)
        entry = ChangeLog.objects.filter(action=ChangeLog.Action.MOVED, location=self.pallet).get()
        self.assertIn("map_position", [change["field"] for change in entry.changes])

    def test_the_move_dialog_places_it_on_the_way(self):
        self.place_all()
        self.client.force_login(self.member)
        target = local_point(20, 0)
        self.client.post(reverse("location_move", args=[self.pallet.pk]),
                         {"parent_location": self.store.pk, "map_geometry": target.json, "map_rotation": "0"})
        self.pallet.refresh_from_db()
        self.assertEqual(self.pallet.parent_location, self.store)
        self.assertLess(geo.distance_m(geo.anchor(self.shape(self.pallet).geometry), target), 0.001)
        self.assertLess(geo.distance_m(self.shape(self.box).geometry, local_point(20.3, 0)), 0.001)

    def test_a_unique_item_moved_elsewhere_loses_its_point_unless_the_dialog_gives_one(self):
        self.place_all()
        self.client.force_login(self.member)
        self.client.post(reverse("move_unique_item", args=[self.saw.pk]),
                         {"location": self.store.pk, "map_point": local_point(21, 0).json})
        self.assertLess(geo.distance_m(UniqueItemPosition.objects.get().point, local_point(21, 0)), 0.001)
        self.client.post(reverse("move_unique_item", args=[self.saw.pk]), {"location": self.box.pk})
        self.assertFalse(UniqueItemPosition.objects.exists())

    def test_building_parts_keep_their_area_when_restructured(self):
        area = geo.rectangle(local_point(20, 0), 5, 5)
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, area)
        self.store.parent_location = self.other_level
        self.store.save()
        self.assertIsNotNone(self.shape(self.store).geometry)

    def test_changes_are_in_the_change_log_with_a_label(self):
        positions.set_location_shape(self.pallet, None, CENTER, 15)
        entry = ChangeLog.objects.filter(location=self.pallet, action=ChangeLog.Action.CHANGED).latest("pk")
        self.assertEqual(entry.changes[0]["field"], "map_position")
        self.assertIn("120 × 80 cm", entry.changes[0]["after"])
        self.member.user_permissions.add(Permission.objects.get(codename="view_changelog"))
        self.client.force_login(self.member)
        response = self.client.get(self.pallet.get_absolute_url())
        self.assertContains(response, "Position on the map")

    def test_invalid_positions_are_refused(self):
        with self.assertRaises(positions.PlacementError):
            positions.set_location_shape(self.pallet, None, '{"type": "Point", "coordinates": [500, 0]}')
        with self.assertRaises(positions.PlacementError):
            positions.set_location_shape(self.store, LocationShape.Kind.AREA, CENTER.json)


@override_settings(LANGUAGE_CODE="en")
class StorageUnitTests(Building, TestCase):
    """Shelves are points or rectangles of the size entered in the dialog; their compartments go where they go."""

    @classmethod
    def setUpTestData(cls):
        cls.build()
        compartment = LocationType.objects.create(name="Fach/Schub", category="storage_unit")
        shelf = LocationType.objects.create(name="Regal", unique=True, moveable=True, category="storage_unit",
                                            sublocation_type=compartment)
        cls.shelf = Location.objects.create(type=shelf, name="Regal 301", short_name="R301", parent_location=cls.store)
        cls.compartment = Location.objects.create(type=compartment, name="Fach a", short_name="a",
                                                  parent_location=cls.shelf)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(Permission.objects.get(codename="change_location"))

    def test_the_dialog_gives_the_size_of_the_rectangle(self):
        self.client.force_login(self.member)
        url = reverse("maps:location_shape", args=[self.shelf.pk])
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle", "map_rotation": "90",
                                          "map_width_cm": "200", "map_depth_cm": "60"})
        self.assertTrue(response.json()["ok"], response.content)
        shape = LocationShape.objects.get(location=self.shelf)
        self.assertEqual((shape.kind, shape.width_cm, shape.depth_cm, shape.rotation), ("rectangle", 200, 60, 90))
        self.assertAlmostEqual(geo.area_m2(shape.geometry), 1.2, places=3)
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "point"})
        self.assertEqual(LocationShape.objects.get(location=self.shelf).kind, "point")
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                                          "map_width_cm": "-3", "map_depth_cm": "60"})
        self.assertFalse(response.json()["ok"])

    def test_the_types_usual_size_comes_first_and_can_be_changed(self):
        LocationTypeMap.objects.create(type=self.shelf.type, placeable=True, default_width_cm=100, default_depth_cm=40)
        self.client.force_login(self.member)
        context = self.client.get(reverse("maps:place_context"), {"location": self.shelf.pk}).json()["own"]
        self.assertEqual((context["kind"], context["size"], context["type_size"]), (None, [1.0, 0.4], [1.0, 0.4]))
        url = reverse("maps:location_shape", args=[self.shelf.pk])
        self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                               "map_width_cm": "100", "map_depth_cm": "40"})
        shape = LocationShape.objects.get(location=self.shelf)
        self.assertEqual((shape.kind, shape.width_cm, shape.depth_cm, shape.size_cm()), ("rectangle", None, None, (100, 40)))
        self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                               "map_width_cm": "180", "map_depth_cm": "50"})
        shape.refresh_from_db()
        self.assertEqual((shape.width_cm, shape.depth_cm), (180, 50))  # its own size

    def test_a_position_can_go_to_another_location(self):
        # The edit mode's change of what a position belongs to: the other one gets it, this one's goes, together.
        other = Location.objects.create(type=self.shelf.type, name="Regal 302", short_name="R302",
                                        parent_location=self.store)
        positions.set_location_shape(self.shelf, None, CENTER)
        self.client.force_login(self.member)
        url = reverse("maps:location_shape", args=[other.pk])
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "point", "take_from": self.shelf.pk})
        self.assertTrue(response.json()["ok"], response.content)
        self.assertIsNotNone(LocationShape.objects.get(location=other).geometry)
        self.assertIsNone(LocationShape.objects.get(location=self.shelf).geometry)
        # Nothing changes when the one it belonged to may not be changed.
        response = self.client.post(reverse("maps:location_shape", args=[self.shelf.pk]),
                                    {"map_geometry": CENTER.json, "map_kind": "point", "take_from": self.compartment.pk})
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(LocationShape.objects.get(location=self.shelf).geometry)

    def test_compartments_are_where_their_shelf_is(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("maps:location_shape", args=[self.compartment.pk]),
                                    {"map_geometry": CENTER.json})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("map-place-modal", self.client.get(self.compartment.get_absolute_url()).content.decode())
        positions.set_location_shape(self.shelf, None, CENTER)
        shape, source, exact = effective_shape(self.compartment)
        self.assertEqual((source, exact), (self.shelf, False))


@override_settings(LANGUAGE_CODE="en")
class ResultMapLinkTests(Building, TestCase):
    """Result rows link to the map (slot result_entry.place); where their locations are in the tree is loaded once for
    the whole list (result_entries.start), not once per row."""

    @classmethod
    def setUpTestData(cls):
        cls.build()
        positions.set_location_shape(cls.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 5, 5))

    def add(self, n):
        box = Location.objects.create(type=self.box_type, name=f"Kiste {n + 10}", short_name=f"K{n + 10}",
                                      parent_location=self.store)
        UniqueItem.objects.create(item=Item.objects.create(name=f"Hobel {n}", kind=Item.Kind.UNIQUE,
                                                           measurement_unit_id=self.saw.item.measurement_unit_id),
                                  location=box)

    def queries(self, url, **params):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url, params)
        return len(captured), response

    def test_the_search_loads_the_tree_once(self):
        self.add(0)
        one, response = self.queries(reverse("index"), q="hobel")
        self.assertContains(response, "On the map")
        for n in range(1, 10):
            self.add(n)
        ten, response = self.queries(reverse("index"), q="hobel")
        self.assertEqual(response.content.decode().count("On the map"), 20)  # each item and its unique item
        self.assertEqual(ten, one)

    def test_not_in_a_locations_own_lists(self):
        self.add(0)
        page = self.client.get(self.store.get_absolute_url()).content.decode()
        lists = page[page.index("data-result-list"):]
        self.assertNotIn("result-map", lists)
