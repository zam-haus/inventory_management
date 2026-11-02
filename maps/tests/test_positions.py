from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from inventory.models import ChangeLog, Item, Location, LocationType, MeasurementUnit, UniqueItem

from .. import geo, positions
from ..levels import Tree, effective_shape
from ..models import ItemMap, LocationShape, LocationTypeMap, UniqueItemPosition
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
            item=Item.objects.create(name="Saw", kind=Item.Kind.SERIALIZED, measurement_unit=unit), location=cls.box)
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
@override_settings(LANGUAGE_CODE="en")
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
        positions.set_item_position(self.saw, None, local_point(0.3, 0.1))

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
        box, saw = self.shape(self.box).geometry, UniqueItemPosition.objects.get().geometry
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
                         {"location": self.store.pk, "map_geometry": local_point(21, 0).json})
        self.assertLess(geo.distance_m(UniqueItemPosition.objects.get().geometry, local_point(21, 0)), 0.001)
        self.client.post(reverse("move_unique_item", args=[self.saw.pk]), {"location": self.box.pk})
        self.assertFalse(UniqueItemPosition.objects.exists())

    def test_unique_items_take_every_shape_with_their_items_usual_size(self):
        ItemMap.objects.create(item=self.saw.item, default_kind="rectangle", default_width_cm=200, default_depth_cm=80)
        position = positions.set_item_position(self.saw, "rectangle", CENTER, 90)
        self.assertEqual((position.kind, position.rotation, position.width_cm), ("rectangle", 90, None))
        self.assertAlmostEqual(geo.area_m2(position.geometry), 1.6, places=3)  # the item's 200 × 80 cm
        position = positions.set_item_position(self.saw, "rectangle", CENTER, 0, size=(100, 50))
        self.assertEqual(position.size_cm(), (100, 50))  # its own
        position = positions.set_item_position(self.saw, "rectangle", CENTER, 0, size=(200, 80))
        self.assertEqual(position.width_cm, None)  # the usual size is not kept as its own
        area = geo.rectangle(local_point(0.5, 0), 2, 1)
        position = positions.set_item_position(self.saw, "area", area)
        self.assertEqual(position.kind, "area")
        self.assertIn("area of 2.0 m²", positions.describe(position))  # 1.998 m², rounded
        self.assertIsNone(positions.set_item_position(self.saw, None, None))
        self.assertFalse(UniqueItemPosition.objects.exists())

    def test_the_unique_items_page_shows_the_change_of_its_position(self):
        positions.set_item_position(self.saw, None, CENTER)
        self.member.user_permissions.add(Permission.objects.get(codename="view_changelog"))
        self.client.force_login(self.member)
        response = self.client.get(self.saw.get_absolute_url())  # its position's relation has the field's name
        self.assertContains(response, "Position on the map")

    def test_the_area_of_a_unique_item_moves_along(self):
        self.place_all()
        positions.set_item_position(self.saw, "area", geo.rectangle(local_point(0.3, 0), 0.4, 0.2))
        positions.set_location_shape(self.pallet, None, local_point(10, 0))
        moved = geo.anchor(UniqueItemPosition.objects.get().geometry)
        self.assertLess(geo.distance_m(moved, local_point(10.3, 0)), 0.001)

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
        # Only that it changed: coordinates, size and area say nothing to people.
        self.assertEqual((entry.changes[0]["before"], entry.changes[0]["after"]), ("", ""))
        self.member.user_permissions.add(Permission.objects.get(codename="view_changelog"))
        self.client.force_login(self.member)
        response = self.client.get(self.pallet.get_absolute_url())
        self.assertRegex(response.content.decode(), r"Position on the map:</span>\s*changed")
        # Also older entries that still have the values.
        entry.changes = [{**entry.changes[0], "after": "point at 49.5, 11.0"}]
        entry.save()
        self.assertNotContains(self.client.get(self.pallet.get_absolute_url()), "49.5, 11.0")

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
        self.assertEqual((shape.kind, shape.size_cm(), shape.rotation), ("rectangle", (200, 60), 90))
        self.assertAlmostEqual(geo.area_m2(shape.geometry), 1.2, places=3)
        self.shelf.refresh_from_db()
        self.assertEqual((self.shelf.width_cm, self.shelf.depth_cm), (200, 60))  # the size it was placed in
        entry = ChangeLog.objects.get(location=self.shelf, action=ChangeLog.Action.CHANGED)  # one, with the position
        self.assertEqual([change["field"] for change in entry.changes], ["width_cm", "depth_cm", "map_position"])
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "point"})
        self.assertEqual(LocationShape.objects.get(location=self.shelf).kind, "point")
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                                          "map_width_cm": "-3", "map_depth_cm": "60"})
        self.assertFalse(response.json()["ok"])

    def test_the_types_usual_size_comes_first_and_the_locations_is_fixed(self):
        LocationTypeMap.objects.create(type=self.shelf.type, placeable=True, default_width_cm=100, default_depth_cm=40)
        self.client.force_login(self.member)
        context = self.client.get(reverse("maps:place_context"), {"location": self.shelf.pk}).json()["own"]
        self.assertEqual((context["kind"], context["size"], context["type_size"], context["size_fixed"]),
                         (None, [1.0, 0.4], [1.0, 0.4], False))
        url = reverse("maps:location_shape", args=[self.shelf.pk])
        self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                               "map_width_cm": "180", "map_depth_cm": "50"})  # another size than the usual one
        shape = LocationShape.objects.get(location=self.shelf)
        self.assertEqual((shape.kind, shape.size_cm(), shape.size_fixed()), ("rectangle", (180, 50), True))
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle",
                                          "map_width_cm": "100", "map_depth_cm": "40"})
        self.assertFalse(response.json()["ok"])  # its dimensions: changed on its page
        self.assertIn("180 × 50 cm", response.json()["error"])
        self.assertTrue(self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "rectangle", "map_rotation": "45",
                                               "map_width_cm": "180", "map_depth_cm": "50"}).json()["ok"])  # turned
        context = self.client.get(reverse("maps:place_context"), {"location": self.shelf.pk}).json()["own"]
        self.assertEqual((context["size"], context["size_fixed"]), ([1.8, 0.5], True))
        Location.objects.filter(pk=self.shelf.pk).update(width_cm=90)
        shape.refresh_from_db()
        self.assertEqual(shape.size_cm(), (90, 50))  # the location's, as it is now

    def test_a_compartment_has_the_size_of_its_shelf(self):
        self.assertIsNone(self.compartment.footprint_cm)
        Location.objects.filter(pk=self.shelf.pk).update(width_cm=120, depth_cm=40, height_cm=200)
        compartment = Location.objects.get(pk=self.compartment.pk)
        self.assertEqual((compartment.footprint_cm, compartment.footprint_source), ((120, 40), self.shelf))
        self.assertEqual(compartment.dimensions_text(), "W 120 × D 40 cm")  # not its height
        Location.objects.filter(pk=self.compartment.pk).update(width_cm=60, depth_cm=40, height_cm=30)
        compartment = Location.objects.get(pk=self.compartment.pk)
        self.assertEqual((compartment.footprint_cm, compartment.dimensions_text()), ((60, 40), "W 60 × D 40 × H 30 cm"))
        self.assertIsNone(self.store.footprint_cm)  # the shelf's room has none of its own

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
        self.assertNotIn("data-map-place", self.client.get(self.compartment.get_absolute_url()).content.decode())
        positions.set_location_shape(self.shelf, None, CENTER)
        shape, source, exact = effective_shape(self.compartment)
        self.assertEqual((source, exact), (self.shelf, False))


@override_settings(LANGUAGE_CODE="en")
class ResultMapTests(Building, TestCase):
    """Result rows show their map after their photos (slot result_entry.slides); where their locations are in the
    tree and when the positions shown were set are loaded once for the whole list (result_entries.start), not once
    per row."""

    @classmethod
    def setUpTestData(cls):
        cls.build()
        positions.set_location_shape(cls.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 5, 5))

    def add(self, n):
        box = Location.objects.create(type=self.box_type, name=f"Kiste {n + 10}", short_name=f"K{n + 10}",
                                      parent_location=self.store)
        UniqueItem.objects.create(item=Item.objects.create(name=f"Hobel {n}", kind=Item.Kind.SERIALIZED,
                                                           measurement_unit_id=self.saw.item.measurement_unit_id),
                                  location=box)

    def queries(self, url, **params):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url, params)
        return len(captured), response

    def row(self, page, obj):
        """The result row of that object."""
        start = page.rindex('<li class="result-entry', 0, page.index(f'class="result-link" href="{obj.get_absolute_url()}"'))
        return page[start:page.index("</li>", start)]

    def test_the_search_loads_the_tree_once(self):
        self.add(0)
        one, response = self.queries(reverse("index"), q="hobel")
        self.assertContains(response, "data-map-slide ")
        for n in range(1, 10):
            self.add(n)
        ten, response = self.queries(reverse("index"), q="hobel")
        page = response.content.decode()
        self.assertEqual(page.count("data-map-slide "), 20)  # each item and its unique item
        self.assertEqual(page.count('id="map-config"'), 1)  # once, for map.js
        self.assertNotIn("On the map", page)  # the map's link is on the map now
        self.assertEqual(ten, one)

    def test_a_row_without_photos_opens_its_map(self):
        self.add(0)
        unique_item = UniqueItem.objects.get(item__name="Hobel 0")
        row = self.row(self.client.get(reverse("index"), {"q": "hobel"}).content.decode(), unique_item)
        self.assertIn(" data-result-viewer>", row)
        self.assertIn('aria-label="Show the preview of Hobel 0">', row)
        self.assertIn('<template data-result-slides>', row)
        # Its box has no position: the store's is shown, highlighted, and the hint says so.
        level = reverse("maps:level_data", args=[-1])
        self.assertIn(f'data-url="{level}" data-focus="loc:{self.store.pk}"', row)
        self.assertIn(f'href="{reverse("maps:level", args=[-1])}?p=loc:{self.store.pk}"', row)
        self.assertIn("Its own position is not known; it is in", row)
        self.assertIn("last set less than a minute ago</time></span>", row)  # the store's, by nobody named
        # Its own position: exact, no hint.
        positions.set_item_position(unique_item, None, local_point(20, 0))
        row = self.row(self.client.get(reverse("index"), {"q": "hobel"}).content.decode(), unique_item)
        self.assertIn(f'data-focus="item:{unique_item.pk}"', row)
        self.assertNotIn("Its own position is not known", row)

    def test_an_items_places_on_one_level_share_a_map(self):
        from inventory.models import ItemLocation
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        glue = Item.objects.create(name="Leim", measurement_unit_id=self.saw.item.measurement_unit_id)
        ItemLocation.objects.create(item=glue, location=self.store, amount=1)
        ItemLocation.objects.create(item=glue, location=self.pallet, amount=2)
        row = self.row(self.client.get(reverse("index"), {"q": "leim"}).content.decode(), glue)
        self.assertEqual(row.count("data-map-slide "), 1)
        focus = {f"loc:{self.hbb.pk}", f"loc:{self.store.pk}"}
        shown = row[row.index('data-focus="') + 12:]
        self.assertEqual(set(shown[:shown.index('"')].split(",")), focus)
        self.assertIn("(its own position is not known; in", row)  # the pallet's: HBB is highlighted
        # A place on another level: a map of its own.
        ground = Location.objects.create(type=self.level.type, name="Werkhaus 0", short_name="WH+0")
        hall = Location.objects.create(type=self.hbb.type, name="Halle", short_name="HAL", parent_location=ground)
        positions.set_location_shape(hall, LocationShape.Kind.AREA, geo.rectangle(local_point(40, 0), 5, 5))
        ItemLocation.objects.create(item=glue, location=hall, amount=3)
        row = self.row(self.client.get(reverse("index"), {"q": "leim"}).content.decode(), glue)
        self.assertEqual(row.count("data-map-slide "), 2)
        self.assertIn(f'data-focus="loc:{hall.pk}"', row)

    def test_who_set_it_only_for_those_who_see_it_in_the_change_log(self):
        from django.contrib.auth import get_user_model
        from inventory.change_log import change_context
        User = get_user_model()
        alex = User.objects.create_user(username="alex", first_name="Alex", last_name="Example")  # invented
        with change_context(actor=alex):
            # Another size: the change log tells only what changed as people read it (positions.describe).
            positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 6, 6))
        self.add(0)
        page = self.client.get(reverse("index"), {"q": "hobel"}).content.decode()
        self.assertNotIn("Alex E.", page)
        viewer = User.objects.create_user(username="viewer")
        viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["view_changelog", "view_changelog_actor"]))
        self.client.force_login(viewer)
        page = self.client.get(reverse("index"), {"q": "hobel"}).content.decode()
        self.assertIn("last set less than a minute ago</time> by Alex E. (alex)", page)
        # The grey box tells the same.
        page = self.client.get(Location.objects.get(short_name="K10").get_absolute_url()).content.decode()
        self.assertIn("by Alex E. (alex)", page[page.index("map-place-around"):])

    def test_not_in_a_locations_own_lists(self):
        self.add(0)
        page = self.client.get(self.store.get_absolute_url()).content.decode()
        lists = page[page.index("data-result-list"):]
        self.assertNotIn("data-map-slide", lists)
        self.assertNotIn("data-result-viewer", lists)


class LocationSizeMigrationTests(TransactionTestCase):
    def test_own_sizes_on_the_map_become_the_locations_and_back(self):
        before = [("inventory", "0052_location_dimensions"), ("maps", "0005_unique_item_shapes")]
        after = [("maps", "0006_location_size_to_location")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            Location = apps.get_model("inventory", "Location")
            Shape = apps.get_model("maps", "LocationShape")
            kind = apps.get_model("inventory", "LocationType").objects.create(name="Regal", unique=True)
            shelves = [Location.objects.create(type=kind, name=f"Regal {n}", short_name=f"R{n}",
                                               unique_identifier=f"R{n}", locatable_identifier=f"R{n}",
                                               descriptive_identifier=f"Regal {n}") for n in (1, 2, 3)]
            Location.objects.filter(pk=shelves[1].pk).update(width_cm=90, depth_cm=30)  # its own already
            for shelf in shelves[:2]:
                Shape.objects.create(location=shelf, kind="rectangle", geometry=CENTER, width_cm=200, depth_cm=60)
            Shape.objects.create(location=shelves[2], kind="rectangle", geometry=CENTER)  # the usual size
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            Location = executor.loader.project_state(after).apps.get_model("inventory", "Location")
            self.assertEqual([(shelf.width_cm, shelf.depth_cm) for shelf in Location.objects.order_by("pk")],
                             [(200, 60), (90, 30), (None, None)])
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            Shape = executor.loader.project_state(before).apps.get_model("maps", "LocationShape")
            self.assertEqual([(shape.width_cm, shape.depth_cm) for shape in Shape.objects.order_by("location_id")],
                             [(200, 60), (90, 30), (None, None)])
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
