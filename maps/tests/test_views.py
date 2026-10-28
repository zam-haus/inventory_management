import io
import math
import json
import shutil
import tempfile
import unittest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import ChangeLog, Location, LocationType
from PIL import Image

from .. import geo, positions, render
from ..models import BackgroundLayer, FloorPlan, LocationShape, LocationTypeMap, SurveyedPoint
from .test_geo import CENTER, local_point
from .test_positions import Building


def png(width=400, height=300):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><script>alert(1)</script>'
       b'<rect width="400" height="300"/></svg>')


@override_settings(LANGUAGE_CODE="en")
class MapViewTests(Building, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()
        User = get_user_model()
        cls.member = User.objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["change_location", "change_uniqueitem"]))
        cls.staff = User.objects.create_user(username="staff", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(
            codename__in=["manage_floorplans", "change_building_shape", "change_location"]))

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def plan(self, data=None, filename="plan.png", **fields):
        from .. import plans
        plan = FloorPlan(**{"level": -1, **fields})
        plan.source.save(filename, SimpleUploadedFile(filename, data or png()), save=False)
        return plans.save(plan)

    def test_the_level_shows_plans_positions_and_stacked_parts(self):
        plan = self.plan(control_points=[{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                                         {"pixel": [400, 0], "lonlat": list(local_point(8, 0).coords)}])
        self.assertTrue(plan.is_placed)
        positions.set_location_shape(self.pallet, None, local_point(1, -1))
        positions.set_item_position(self.saw, local_point(1, -1.2))
        data = self.client.get(reverse("maps:level_data", args=[-1])).json()
        self.assertEqual([p["id"] for p in data["plans"]], [plan.pk])
        features = {f["properties"]["id"]: f["properties"] for f in data["features"]["features"]}
        self.assertEqual(features[f"loc:{self.pallet.pk}"]["stack"], [self.hbb.pk, self.upper.pk])
        self.assertEqual(features[f"loc:{self.pallet.pk}"]["kind"], "rectangle")
        self.assertIn(f"item:{self.saw.pk}", features)
        self.assertEqual([part["short"] for part in data["stacks"][0]["parts"]], [".1", ".2"])
        page = self.client.get(reverse("maps:level", args=[-1]))
        self.assertContains(page, "data-map-page")
        self.assertContains(page, ">-1</a>")
        self.assertContains(page, "data-map-measure-toggle")  # measuring, also for guests
        config = json.loads(page.content.decode().split('<script id="map-config" type="application/json">')[1]
                            .split("</script>")[0])
        self.assertEqual([layer["default"] for layer in config["layers"] if layer.get("default")], [True])
        BackgroundLayer.objects.update(active=False)
        page = self.client.get(reverse("maps:level", args=[-1]))
        self.assertContains(page, '"layers": []')

    def test_levels_are_listed_top_down(self):
        Location.objects.create(type=self.level.type, name="Werkhaus +1", short_name="WH+1")
        Location.objects.create(type=self.level.type, name="Haupthaus -2", short_name="HH-2")
        page = self.client.get(reverse("maps:level", args=[-1]))
        self.assertEqual([n for n, _label, _codes in page.context["levels"]], [1, -1, -2])

    def test_what_is_placed_is_set_per_location_type_in_the_admin(self):
        self.client.force_login(self.member)
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        self.assertNotIn("data-place-edit", self.client.get(self.pallet.get_absolute_url()).content.decode())
        admin = get_user_model().objects.create_superuser("admin")
        self.client.force_login(admin)
        change = reverse("admin:inventory_locationtype_change", args=[self.pallet_type.pk])
        page = self.client.get(change)
        self.assertContains(page, "map_settings-0-placeable")  # the inline on the location type's page
        form = page.context["adminform"].form
        data = {name: value for name, value in form.initial.items() if value is not None and not isinstance(value, list)}
        data.update({
            "name": self.pallet_type.name, "category": "container", "unique": "on", "moveable": "on",
            "map_settings-TOTAL_FORMS": "1", "map_settings-INITIAL_FORMS": "1", "map_settings-MIN_NUM_FORMS": "0",
            "map_settings-MAX_NUM_FORMS": "1", "map_settings-0-id": LocationTypeMap.objects.get(type=self.pallet_type).pk,
            "map_settings-0-type": self.pallet_type.pk, "map_settings-0-placeable": "on",
            "map_settings-0-as_point": "on", "map_settings-0-as_rectangle": "on",
            "map_settings-0-default_width_cm": "120", "map_settings-0-default_depth_cm": "80"})
        response = self.client.post(change, data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and
                         response.context["adminform"].form.errors)
        self.assertTrue(LocationTypeMap.objects.get(type=self.pallet_type).placeable)
        self.client.force_login(self.member)
        self.assertIn("data-place-edit", self.client.get(self.pallet.get_absolute_url()).content.decode())

    def test_staff_edit_and_move_everything_on_the_map(self):
        area = geo.rectangle(local_point(20, 0), 5, 5).json
        url = reverse("maps:location_shape", args=[self.store.pk])
        self.client.force_login(self.member)  # changes locations, but not building parts, and no map editor
        self.assertEqual(self.client.post(url, {"map_geometry": area}).status_code, 403)
        page = self.client.get(reverse("maps:level", args=[-1])).content.decode()
        self.assertNotIn("data-map-edit-toggle", page)
        self.assertIn("Edit the map", page)  # disabled, with the reason
        editor = get_user_model().objects.create_user(username="editor", is_staff=True)  # staff, no permissions
        self.client.force_login(editor)
        page = self.client.get(reverse("maps:level", args=[-1])).content.decode()
        self.assertIn("data-map-edit-toggle", page)
        self.assertIn("map_edit.js", page)
        self.assertTrue(self.client.post(url, {"map_geometry": area}).json()["ok"])
        self.assertEqual(LocationShape.objects.get(location=self.store).kind, LocationShape.Kind.AREA)
        # Not what is not placed on the map at all (containers, for now).
        response = self.client.post(reverse("maps:location_shape", args=[self.pallet.pk]), {"map_geometry": CENTER.json})
        self.assertEqual(response.status_code, 403)
        self.client.logout()
        page = self.client.get(reverse("maps:level", args=[-1])).content.decode()
        self.assertNotIn("data-map-edit-toggle", page)
        self.assertNotIn("Edit the map", page)  # guests: nothing

    def test_new_positions_go_to_locations_without_one(self):
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        url = reverse("maps:unplaced", args=[-1])
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)  # the edit mode's, for map editors
        self.client.force_login(self.staff)
        areas = [row["code"] for row in self.client.get(url, {"kind": "area"}).json()["locations"]]
        self.assertEqual(areas, ["HBB.1", "HBB.2", "HH-1", "LAG", "WH-1"])  # not HBB, which has one
        self.assertEqual(self.client.get(url).json()["locations"], [])  # pallets and boxes: not placeable for now
        LocationTypeMap.objects.filter(type=self.pallet_type).update(placeable=True)
        rows = self.client.get(url).json()["locations"]
        self.assertEqual([(row["code"], row["size"]) for row in rows], [("P1", [1.2, 0.8])])

    def test_a_row_of_shelves_is_placed_together(self):
        shelf = LocationType.objects.create(name="Regal", unique=True, moveable=True, category="storage_unit")
        shelves = [Location.objects.create(type=shelf, name=f"Regal 30{n}", short_name=f"R30{n}",
                                           parent_location=self.store) for n in (1, 2, 3)]
        url = reverse("maps:location_shape_row")
        middles = [local_point(x, 0) for x in (0, 1, 2)]  # 1 m wide, side by side
        rows = [{"pk": location.pk, "kind": "rectangle", "geometry": middle.json, "rotation": 30, "width_cm": 100,
                 "depth_cm": 50} for location, middle in zip(shelves, middles)]
        self.assertEqual(self.client.post(url, {"rows": json.dumps(rows)}).status_code, 403)  # not logged in
        self.client.force_login(self.staff)
        unplaced = self.client.get(reverse("maps:unplaced", args=[-1]), {"kind": "rectangle"}).json()["locations"]
        self.assertEqual([(row["code"], row["type"]) for row in unplaced], [(f"R30{n}", shelf.pk) for n in (1, 2, 3)])
        # One that does not exist: none is placed.
        broken = rows[:2] + [{**rows[2], "pk": 999999}]
        self.assertEqual(self.client.post(url, {"rows": json.dumps(broken)}).status_code, 404)
        self.assertFalse(LocationShape.objects.filter(location__in=shelves).exists())
        self.assertFalse(self.client.post(url, {"rows": json.dumps(rows[:1] * 2)}).json()["ok"])  # twice the same
        self.assertEqual(self.client.post(url, {"rows": json.dumps(rows)}).json(), {"ok": True, "placed": 3})
        shapes = [LocationShape.objects.get(location=location) for location in shelves]
        self.assertEqual({(shape.kind, shape.width_cm, shape.depth_cm, shape.rotation) for shape in shapes},
                         {("rectangle", 100, 50, 30.0)})
        self.assertAlmostEqual(geo.local(shapes[0].geometry.centroid).distance(geo.local(shapes[1].geometry.centroid)),
                               1, places=2)
        self.assertEqual(ChangeLog.objects.filter(location__in=shelves, action=ChangeLog.Action.CHANGED).count(), 3)
        # Side by side along the grid's x axis (turned by the meridian convergence from true north, as the map draws
        # the row): neighbours share an edge, none is turned on its own.
        turn = -geo.true_north(middles[1])
        rows = [{**row, "rotation": turn} for row in rows]
        self.assertTrue(self.client.post(url, {"rows": json.dumps(rows)}).json()["ok"])
        rings = [geo.local(LocationShape.objects.get(location=location).geometry).shell.coords for location in shelves]
        for left, right in zip(rings, rings[1:]):
            self.assertLess(math.dist(left[1], right[0]), 0.002)  # top right of one, top left of the next
            self.assertLess(math.dist(left[2], right[3]), 0.002)

    def test_the_shapes_a_type_allows(self):
        self.client.force_login(self.staff)
        # Defaults by category: building parts areas, storage units and containers points and rectangles.
        context = self.client.get(reverse("maps:place_context"), {"location": self.store.pk}).json()["own"]
        self.assertEqual(context["kinds"], ["area"])
        url = reverse("maps:location_shape", args=[self.store.pk])
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "point"})
        self.assertIn("not placed as Point", response.json()["error"])
        # Set in the admin: LAG and its kind may also be a point; the list of new positions follows.
        LocationTypeMap.objects.create(type=self.store.type, as_point=True, as_rectangle=False, as_area=True)
        self.assertTrue(self.client.post(url, {"map_geometry": CENTER.json, "map_kind": "point"}).json()["ok"])
        context = self.client.get(reverse("maps:place_context"), {"location": self.store.pk}).json()["own"]
        self.assertEqual(context["kinds"], ["point", "area"])
        unplaced = reverse("maps:unplaced", args=[-1])
        points = [row["code"] for row in self.client.get(unplaced, {"kind": "point"}).json()["locations"]]
        rectangles = [row["code"] for row in self.client.get(unplaced, {"kind": "rectangle"}).json()["locations"]]
        self.assertEqual((points, rectangles), (["HBB"], []))  # Bereich: point and area; LAG has its point already
        with self.assertRaises(ValidationError):
            LocationTypeMap(type=self.pallet_type, as_point=False, as_rectangle=False, as_area=False).clean()

    def test_removing_an_area(self):
        # The dialog and the edit mode send no kind when removing (it failed with a NOT NULL error).
        self.client.force_login(self.staff)
        url = reverse("maps:location_shape", args=[self.store.pk])
        self.client.post(url, {"map_geometry": geo.rectangle(local_point(20, 0), 5, 5).json, "map_kind": "area"})
        response = self.client.post(url, {"map_geometry": ""})
        self.assertTrue(response.json()["ok"], response.content)
        shape = LocationShape.objects.get(location=self.store)
        self.assertEqual((shape.geometry, shape.kind), (None, LocationShape.Kind.AREA))
        entry = ChangeLog.objects.filter(location=self.store).latest("pk")
        self.assertEqual(entry.changes[0]["after"], "")
        self.assertTrue(self.client.post(url, {"map_geometry": ""}).json()["ok"])  # again: nothing to remove

    def test_the_location_window_shows_a_small_map(self):
        info = reverse("location_info", args=[self.pallet.pk])
        self.assertNotIn("data-map-mini", self.client.get(info).content.decode())  # nothing on the map yet
        self.assertIn("maps/map_mini.js", self.client.get(reverse("index")).content.decode())  # on every page
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        window = self.client.get(info).content.decode()
        self.assertIn('data-map-mini data-url="/map/level/-1/data/" data-focus="loc:%d"' % self.hbb.pk, window)
        self.assertIn("Its own position is not known", window)
        self.assertIn('id="map-config"', window)

    def test_floor_plans_need_their_own_permission(self):
        plan = self.plan()
        user = get_user_model().objects.create_user(username="planner", is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(codename__in=["add_floorplan", "change_floorplan"]))
        self.client.force_login(user)  # the model permissions (admin) are not enough
        for url in (reverse("maps:plans"), reverse("maps:plan_align", args=[plan.pk]),
                    reverse("maps:plan_source", args=[plan.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertNotIn(reverse("maps:plans"), self.client.get(reverse("maps:level", args=[-1])).content.decode())
        self.client.force_login(get_user_model().objects.create_superuser("admin"))
        self.assertEqual(self.client.get(reverse("maps:plans")).status_code, 200)
        self.assertEqual(self.client.get(reverse("maps:plans")).context["form"]["dpi"].value(), 300)

    def test_the_map_edit_permission_for_others(self):
        user = get_user_model().objects.create_user(username="mapper")
        user.user_permissions.add(Permission.objects.get(codename="edit_map"))
        self.client.force_login(user)
        response = self.client.post(reverse("maps:location_shape", args=[self.store.pk]),
                                    {"map_geometry": geo.rectangle(local_point(20, 0), 5, 5).json})
        self.assertTrue(response.json()["ok"])

    def test_look_and_label_per_location_type(self):
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        positions.set_location_shape(self.upper, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 4, 4))
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 5, 5))

        def features():
            data = self.client.get(reverse("maps:level_data", args=[-1])).json()
            return {f["properties"]["code"]: (f["properties"]["label"], f["properties"]["style"])
                    for f in data["features"]["features"]}

        # Without settings: purpose or name, the code chip below; a stacked part with its area's code.
        self.assertEqual(features(), {
            "HBB": ({"title": "Holzbaubühne", "code": "HBB", "min_zoom": None, "style": {}}, {}),
            "HBB.2": ({"title": "oben", "code": "HBB.2", "min_zoom": None, "style": {}}, {}),
            "LAG": ({"title": "Lager", "code": "LAG", "min_zoom": None, "style": {}}, {})})
        LocationTypeMap.objects.create(type=self.hbb.type, color="#123456", fill_opacity=0.3, line_width=2,
                                       label="{name} ({short})", label_min_zoom=19)
        LocationTypeMap.objects.create(type=self.upper.type, label="-")
        look = {"color": "#123456", "fillOpacity": 0.3, "weight": 2.0}
        self.assertEqual(features(), {
            "HBB": ({"title": "Holzbaubühne (HBB)", "code": "HBB", "min_zoom": 19, "style": {}}, look),
            "HBB.2": ({"title": "", "code": ""}, {}),
            "LAG": ({"title": "Lager (LAG)", "code": "LAG", "min_zoom": 19, "style": {}}, look)})
        # More of Leaflet's options as JSON, the fields above them; label size, colour, weight.
        LocationTypeMap.objects.filter(type=self.hbb.type).update(
            style_options={"dashArray": "6 4", "lineJoin": "round", "fill": False, "color": "#ff0000"},
            label_size=14, label_color="#003366", label_bold=True)
        hbb = features()["HBB"]
        self.assertEqual(hbb[1], {"dashArray": "6 4", "lineJoin": "round", "fill": False, "color": "#123456",
                                  "fillOpacity": 0.3, "weight": 2.0})
        self.assertEqual(hbb[0]["style"], {"fontSize": "14px", "color": "#003366", "fontWeight": "700"})
        for options in ({"className": "x"}, {"dashArray": "6px"}, {"weight": 50}, {"fill": "no"}, ["dashArray"]):
            with self.subTest(options), self.assertRaises(ValidationError):
                LocationTypeMap(type=self.pallet_type, style_options=options).clean()
        LocationTypeMap(type=self.pallet_type, style_options={"radius": 4, "stroke": False}).clean()
        for label in ("{nope}", "{code", "{0}"):
            with self.subTest(label), self.assertRaises(ValidationError):
                LocationTypeMap(type=self.pallet_type, label=label).clean()
        with self.assertRaises(ValidationError):
            LocationTypeMap(type=self.pallet_type, color="red").full_clean(exclude=["type"])

    def test_background_layers_are_set_in_the_admin(self):
        self.assertEqual(list(BackgroundLayer.objects.values_list("name", "is_default")),
                         [("Luftbild Erlangen 2018", True), ("Luftbild Bayern (DOP20)", False),
                          ("RRZE Tileserver (osm.de-Stil)", False)])
        osm = BackgroundLayer.objects.get(name__startswith="RRZE")
        osm.is_default = True
        osm.save()  # the new default replaces the old one
        self.assertEqual(list(BackgroundLayer.objects.filter(is_default=True)), [osm])
        for url in ("http://tiles.example.org/{z}/{x}/{y}.png", "https://tiles.example.org/{z}/{x}.png"):
            with self.subTest(url), self.assertRaises(ValidationError):
                BackgroundLayer(name="Other", url=url).clean()
        with self.assertRaises(ValidationError):
            BackgroundLayer(name="Off", url="https://t.example.org/{z}/{x}/{y}.png", active=False,
                            is_default=True).clean()
        admin = get_user_model().objects.create_superuser("admin")
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("admin:maps_backgroundlayer_changelist")), "Luftbild Bayern")

    def test_map_links_name_what_is_shown(self):
        # One parameter: the level in the path, #p= what the map highlights and opens (map.js).
        positions.set_location_shape(self.pallet, None, CENTER)
        page = self.client.get(reverse("view_unique_item", args=[self.saw.pk])).content.decode()
        self.assertIn(f'href="/map/-1/#p=loc:{self.pallet.pk}"', page)  # the saw is on the pallet
        self.assertNotIn("?focus=", page)
        self.assertEqual(self.client.get(reverse("maps:map") + "?focus=x").context["number"], -1)  # ignored

    def test_containers_and_unique_items_are_not_placed_for_now(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("maps:location_shape", args=[self.pallet.pk]), {"map_geometry": CENTER.json})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("maps:item_position", args=[self.saw.pk]), {"map_point": CENTER.json})
        self.assertEqual(response.status_code, 403)
        page = self.client.get(self.pallet.get_absolute_url()).content.decode()
        self.assertNotIn("map-place-modal", page)  # nothing to show, nothing to place: no "Position"
        self.assertNotIn("#p=", page)
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(20, 0), 5, 5))
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        page = self.client.get(self.pallet.get_absolute_url()).content.decode()
        self.assertIn(f"/map/-1/#p=loc:{self.hbb.pk}", page)  # shown by HBB, the area it is in
        self.assertIn("map-place-modal", page)  # to look at
        self.assertNotIn("data-place-edit", page)  # but not to place

    @override_settings(MAPS_PLACE_UNIQUE_ITEMS=True)
    def test_the_position_button_opens_the_map_editing_is_explicit(self):
        positions.set_location_shape(self.hbb, LocationShape.Kind.AREA, geo.rectangle(local_point(5, 0), 5, 5))
        guest = self.client.get(self.store.get_absolute_url()).content.decode()
        self.assertNotIn("map-place-modal", guest)  # nothing to show yet, and guests do not place
        guest = self.client.get(self.upper.get_absolute_url()).content.decode()
        self.assertIn("map-place-modal", guest)  # shown by HBB
        self.assertNotIn("data-place-edit", guest)
        self.assertNotIn("Change the position", guest)  # guests do not see the disabled "Edit"
        self.client.force_login(self.member)  # may change locations, but not building parts
        page = self.client.get(self.upper.get_absolute_url()).content.decode()
        self.assertNotIn("data-place-edit", page)
        self.assertIn("Change the position", page)  # disabled, with the reason
        self.assertIn("Show on the map", page)
        self.client.force_login(self.staff)
        page = self.client.get(self.store.get_absolute_url()).content.decode()
        self.assertIn("data-place-edit", page)  # may place it, even though nothing is shown yet
        self.assertNotIn("Show on the map", page)

    def test_saving_positions_needs_the_permissions(self):
        LocationTypeMap.objects.filter(type=self.pallet_type).update(placeable=True)
        url = reverse("maps:location_shape", args=[self.pallet.pk])
        self.assertEqual(self.client.post(url, {"map_geometry": CENTER.json}).status_code, 403)
        self.client.force_login(self.member)
        response = self.client.post(url, {"map_geometry": CENTER.json, "map_rotation": "45"})
        self.assertTrue(response.json()["ok"], response.content)
        self.assertEqual(LocationShape.objects.get(location=self.pallet).rotation, 45)
        area = geo.rectangle(local_point(20, 0), 5, 5).json
        response = self.client.post(reverse("maps:location_shape", args=[self.store.pk]), {"map_geometry": area})
        self.assertEqual(response.status_code, 403)  # building parts need change_building_shape
        self.client.force_login(self.staff)
        response = self.client.post(reverse("maps:location_shape", args=[self.store.pk]), {"map_geometry": area})
        self.assertEqual(LocationShape.objects.get(location=self.store).kind, LocationShape.Kind.AREA)
        at = self.client.get(reverse("maps:area_at"), {"level": "-1", "lon": local_point(20, 1).x,
                                                      "lat": local_point(20, 1).y}).json()
        self.assertEqual(at["area"]["pk"], self.store.pk)

    @override_settings(MAPS_PLACE_UNIQUE_ITEMS=True)
    def test_unique_item_positions(self):
        self.client.force_login(self.member)
        url = reverse("maps:item_position", args=[self.saw.pk])
        self.assertTrue(self.client.post(url, {"map_point": CENTER.json}).json()["ok"])
        context = self.client.get(reverse("maps:place_context"), {"item": self.saw.pk}).json()
        self.assertEqual(context["level"], -1)
        self.assertEqual(context["own"]["geometry"]["type"], "Point")
        self.assertTrue(self.client.post(url, {"map_point": ""}).json()["ok"])
        self.assertIsNone(positions.item_point(self.saw))

    def test_plan_images_are_public_sources_for_staff_only(self):
        plan = self.plan(SVG, filename="plan.svg")
        image = self.client.get(reverse("maps:plan_image", args=[plan.pk]))
        self.assertEqual(image["Content-Security-Policy"], "sandbox")
        self.assertEqual(image["Content-Type"], "image/svg+xml")
        self.assertEqual(self.client.get(reverse("maps:plan_source", args=[plan.pk])).status_code, 403)
        self.client.force_login(self.staff)
        source = self.client.get(reverse("maps:plan_source", args=[plan.pk]))
        self.assertEqual(source.status_code, 200)
        self.assertIn("attachment", source["Content-Disposition"])

    def test_upload_keeps_the_file_name_and_notes(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("maps:plans"), {
            "level": "-1", "name": "EG", "page": 1, "dpi": 150, "notes": "From the survey of Feb. 2023, sheet 3",
            "source": SimpleUploadedFile("2022-042 EG (Nord).png", png(), content_type="image/png")})
        plan = FloorPlan.objects.get()
        self.assertEqual((plan.source_name, plan.notes), ("2022-042_EG_Nord.png", "From the survey of Feb. 2023, sheet 3"))
        download = self.client.get(reverse("maps:plan_source", args=[plan.pk]))
        self.assertIn('filename="2022-042_EG_Nord.png"', download["Content-Disposition"])
        page = self.client.get(reverse("maps:plan_align", args=[plan.pk]))
        self.assertContains(page, "2022-042_EG_Nord.png")
        self.client.post(reverse("maps:plan_align", args=[plan.pk]), {"action": "settings", "opacity": "0.8",
                                                                      "active": "1", "shown": "1", "notes": "Sheet 4"})
        plan.refresh_from_db()
        self.assertEqual(plan.notes, "Sheet 4")
        self.assertNotIn("Sheet 4", self.client.get(reverse("maps:level_data", args=[-1])).content.decode())

    def test_upload_crop_and_place(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("maps:plans"), {
            "level": "-1", "name": "EG", "page": 1, "dpi": 150,
            "source": SimpleUploadedFile("eg.png", png(), content_type="image/png")})
        plan = FloorPlan.objects.get()
        self.assertRedirects(response, reverse("maps:plan_align", args=[plan.pk]))
        self.assertContains(self.client.get(response.url), "map-align-config")
        image_url = self.client.get(response.url).context["config"]["tiles"][0]["url"]
        self.client.post(response.url, {"action": "crop", "crop": "[0.25, 0, 0.75, 1]"})
        plan.refresh_from_db()
        self.assertEqual((plan.image_width, plan.image_height), (200, 300))
        # A new image, a new URL: browsers keep the old one for a day.
        self.assertNotEqual(self.client.get(response.url).context["config"]["tiles"][0]["url"], image_url)
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                  {"pixel": [200, 0], "lonlat": list(local_point(4, 0).coords)}]
        self.client.post(response.url, {"action": "place", "control_points": json.dumps(points)})
        plan.refresh_from_db()
        self.assertTrue(plan.is_placed)
        self.assertLess(plan.residual_m, 0.01)
        self.assertAlmostEqual(geo.area_m2(plan.outline), 4 * 6, places=1)  # 2 cm per pixel
        # Cropping a placed plan keeps it where it is: its points stay at their places on the page.
        corner = geo.local(plan.corners[0])
        self.client.post(response.url, {"action": "crop", "crop": "[0.5, 0.5, 0.75, 1]"})  # the right half of it
        plan.refresh_from_db()
        self.assertEqual((plan.image_width, plan.image_height), (100, 150))
        self.assertEqual([point["pixel"] for point in plan.control_points], [[-100.0, -150.0], [100.0, -150.0]])
        self.assertLess(plan.residual_m, 0.01)
        self.assertAlmostEqual(geo.area_m2(plan.outline), 2 * 3, places=1)
        top_left = geo.local(plan.corners[0])
        self.assertAlmostEqual(top_left.x - corner.x, 2, places=2)  # 100 px × 2 cm east of the old corner
        self.assertAlmostEqual(corner.y - top_left.y, 3, places=2)  # 150 px × 2 cm south

    def test_the_crop_is_drawn_on_the_whole_page(self):
        plan = self.plan(crop=[0.5, 0, 1, 1])
        self.assertEqual(plan.image_width, 200)
        url = reverse("maps:plan_page", args=[plan.pk])
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)  # the page shows what the crop leaves off
        self.client.force_login(self.staff)
        config = self.client.get(reverse("maps:plan_align", args=[plan.pk])).context["config"]
        self.assertEqual(config["crop"], [[0.5, 0], [1, 0], [1, 1], [0.5, 1]])
        response = self.client.get(config["page"])
        self.assertIn("private", response["Cache-Control"])
        page = Image.open(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual((page.format, page.size), ("WEBP", (400, 300)))
        svg = self.plan(SVG, filename="plan.svg")
        self.assertEqual(self.client.get(reverse("maps:plan_page", args=[svg.pk])).status_code, 404)

    def test_surveyed_points_are_offered_for_placing(self):
        self.assertEqual(SurveyedPoint.objects.count(), 5)  # ZAM's, from the migration
        passerelle = SurveyedPoint.objects.get(name="WH: Übergangsecke Passerelle")
        self.assertEqual((passerelle.latitude, passerelle.longitude), (49.60023103, 11.00210977))
        SurveyedPoint.objects.exclude(pk=passerelle.pk).update(active=False)
        plan = self.plan()
        self.client.force_login(self.staff)
        page = self.client.get(reverse("maps:plan_align", args=[plan.pk]))
        self.assertEqual(page.context["config"]["surveyedPoints"],
                         [{"name": "WH: Übergangsecke Passerelle", "lonlat": [11.00210977, 49.60023103]}])
        self.assertContains(page, "data-align-surveyed")

    def test_cropping_comes_after_placing_and_keeps_changed_points(self):
        plan = self.plan()
        other = self.plan(name="Other sheet", level=0, crop=[[0, 0], [0.5, 0], [0, 0.5]])
        self.client.force_login(self.staff)
        url = reverse("maps:plan_align", args=[plan.pk])
        context = self.client.get(url).context
        self.assertEqual(context["crop_denied"], "Place the plan first.")
        self.assertEqual(context["other_crops"], [{"pk": other.pk, "label": "Other sheet (+0)"}])
        self.assertEqual(context["config"]["otherCrops"], {str(other.pk): other.crop})
        self.assertIsNone(context["config"]["planLayer"])
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                  {"pixel": [400, 0], "lonlat": list(local_point(8, 0).coords)}]
        self.client.post(url, {"action": "place", "control_points": json.dumps(points)})
        context = self.client.get(url).context
        self.assertIsNone(context["crop_denied"])
        self.assertEqual(context["config"]["planLayer"]["id"], plan.pk)  # shown on the right, also when inactive
        # A point dragged after placing comes along with the crop and stays at its place on the page.
        dragged = [points[0], {"pixel": [200, 0], "lonlat": list(local_point(4, 0).coords)}]
        self.client.post(url, {"action": "crop", "crop": "[0.5, 0, 1, 1]", "control_points": json.dumps(dragged),
                               "affine": ""})
        plan.refresh_from_db()
        self.assertEqual([point["pixel"] for point in plan.control_points], [[-200.0, 0.0], [0.0, 0.0]])
        self.assertLess(plan.residual_m, 0.01)

    def test_the_placement_is_copied_from_another_plan(self):
        # Another sheet, placed on its whole page; this one cropped to the right half: the points come at the same
        # places on the page, in pixels of this plan.
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords), "name": "Corner"},
                  {"pixel": [400, 0], "lonlat": list(local_point(8, 0).coords)}]
        other = self.plan(name="Other sheet", level=0, control_points=points, affine=True)
        self.plan(name="Not placed", level=0)
        plan = self.plan(crop=[0.5, 0, 1, 1])
        self.client.force_login(self.staff)
        url = reverse("maps:plan_align", args=[plan.pk])
        context = self.client.get(url).context
        self.assertEqual(context["other_placements"], [{"pk": other.pk, "label": "Other sheet (+0)"}])
        copied = context["config"]["otherPlacements"][str(other.pk)]
        self.assertEqual([point["pixel"] for point in copied["controlPoints"]], [[-200.0, 0.0], [200.0, 0.0]])
        self.assertEqual((copied["controlPoints"][0]["name"], copied["affine"]), ("Corner", True))
        self.client.post(url, {"action": "place", "control_points": json.dumps(copied["controlPoints"])})
        plan.refresh_from_db()
        self.assertLess(plan.residual_m, 0.01)

    def test_a_new_source_file_keeps_placement_and_crop(self):
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                  {"pixel": [200, 0], "lonlat": list(local_point(8, 0).coords)}]
        plan = self.plan(crop=[0.5, 0, 1, 1], control_points=points)  # 400 × 300, the right half: 200 pixels wide
        corners = plan.corners
        old_source = plan.source.name
        self.client.force_login(self.staff)
        url = reverse("maps:plan_align", args=[plan.pk])
        # The revised drawing, scanned at twice the resolution: the same places on the page.
        response = self.client.post(url, {"action": "source", "page": "1", "source": SimpleUploadedFile(
            "revised.png", png(800, 600), content_type="image/png")}, follow=True)
        self.assertContains(response, "keeps its placement and crop")
        plan.refresh_from_db()
        self.assertNotEqual(plan.source.name, old_source)
        self.assertEqual((plan.source_name, plan.image_width, plan.crop), ("revised.png", 400,
                                                                           [[0.5, 0], [1, 0], [1, 1], [0.5, 1]]))
        self.assertEqual([point["pixel"] for point in plan.control_points], [[0.0, 0.0], [400.0, 0.0]])
        self.assertTrue(all(a.distance(b) < 1e-9 for a, b in zip(plan.corners, corners)))  # where it was
        # Another page of the same file is another drawing: it starts without control points.
        plan.page = 2
        from .. import plans
        plans.save(plan)
        self.assertEqual((plan.control_points, plan.is_placed), ([], False))
        # An SVG cannot be cropped here: its crop goes, the points stay at their places on the page.
        plan.control_points = points
        plans.save(plan, rendered=False)
        self.client.post(url, {"action": "source", "source": SimpleUploadedFile("plan.svg", SVG, content_type="image/svg+xml")})
        plan.refresh_from_db()
        self.assertIsNone(plan.crop)
        # Pixel 0 and 200 of the right half (400 wide) were at 1/2 and 3/4 of the page: 200 and 300 of the SVG.
        self.assertEqual([point["pixel"] for point in plan.control_points], [[200.0, 0.0], [300.0, 0.0]])
        self.assertTrue(plan.is_placed)
        response = self.client.post(url, {"action": "source", "page": "x", "source": SimpleUploadedFile(
            "again.png", png(), content_type="image/png")}, follow=True)
        self.assertContains(response, "The page is a number from 1.")

    def test_an_empty_crop_is_the_whole_page(self):
        # An empty crop (e.g. "[]" saved in the admin) made the next crop fail with "needs four numbers".
        plan = self.plan(crop=[])
        self.assertIsNone(plan.crop)
        FloorPlan.objects.filter(pk=plan.pk).update(crop=[])
        self.client.force_login(self.staff)
        url = reverse("maps:plan_align", args=[plan.pk])
        self.client.post(url, {"action": "crop", "crop": "[0.5, 0, 1, 1]"})
        plan.refresh_from_db()
        self.assertEqual((plan.crop, plan.image_width), ([[0.5, 0], [1, 0], [1, 1], [0.5, 1]], 200))
        response = self.client.post(url, {"action": "crop", "crop": "[null, null, null, null]"}, follow=True)
        self.assertContains(response, "outline of at least three corners")
        plan.refresh_from_db()
        self.assertEqual(plan.crop, [[0.5, 0], [1, 0], [1, 1], [0.5, 1]])

    def test_an_outline_crop_leaves_the_rest_transparent(self):
        plan = self.plan()
        self.client.force_login(self.staff)
        triangle = [[0, 0], [1, 0], [0, 1]]
        self.client.post(reverse("maps:plan_align", args=[plan.pk]), {"action": "crop", "crop": json.dumps(triangle)})
        plan.refresh_from_db()
        image = Image.open(plan.image.path)
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.getpixel((10, 10))[3], 255)  # inside
        self.assertEqual(image.getpixel((390, 290))[3], 0)  # outside the outline

    def test_removing_the_background(self):
        data = io.BytesIO()
        drawing = Image.new("RGB", (40, 20), "white")
        drawing.paste((200, 0, 0), (0, 0, 10, 20))  # a red wall on white paper
        drawing.save(data, "PNG")
        plan = self.plan(data.getvalue())
        self.client.force_login(self.staff)
        self.client.post(reverse("maps:plan_align", args=[plan.pk]),
                         {"action": "settings", "opacity": "0.8", "active": "1", "transparent": "1"})
        plan.refresh_from_db()
        self.assertTrue(plan.transparent)
        image = Image.open(plan.image.path).convert("RGBA")
        self.assertEqual(image.getpixel((30, 10))[3], 0)  # the paper
        red, green, blue, alpha = image.getpixel((5, 10))
        self.assertEqual(alpha, 255)
        self.assertGreater(red, 150)
        self.assertLess(green, 30)

    def test_the_crop_is_checked_in_the_admin(self):
        plan = self.plan()
        for crop, ok in (([], True), (None, True), ([0.1, 0.2, 0.9, 0.8], True), ([[0, 0], [1, 0], [0, 1]], True),
                         ("0.1,0.2,0.9,0.8", False), ([0.1, 0.2, 0.9], False), ([0.9, 0, 0.1, 1], False),
                         ([[0, 0], [1, 0]], False), ([[0, 0], [1, 1], [0.5, 0.5]], False), ([[0, 0], [2, 0], [0, 1]], False)):
            with self.subTest(crop):
                plan.crop = crop
                if ok:
                    plan.clean()
                else:
                    with self.assertRaises(ValidationError):
                        plan.clean()

    def test_large_plans_are_tiled(self):
        # 5000 × 300 pixels: three tiles of at most 2048 (+2 overlapping the next) across, one row.
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                  {"pixel": [5000, 0], "lonlat": list(local_point(50, 0).coords)}]
        plan = self.plan(png(5000, 300), control_points=points)
        self.assertEqual((plan.image_width, plan.image_height), (5000, 300))
        self.assertEqual([(t["x"], t["y"], t["w"], t["h"]) for t in plan.tiles],
                         [(0, 0, 2050, 300), (2048, 0, 2050, 300), (4096, 0, 904, 300)])
        self.assertEqual(Image.open(plan.image.path).size, (2048, 123))  # the preview
        tiles = self.client.get(reverse("maps:level_data", args=[-1])).json()["plans"][0]["tiles"]
        self.assertEqual(len(tiles), 3)
        tile = self.client.get(tiles[1]["url"])
        self.assertEqual((tile.status_code, tile["Content-Type"], tile["Content-Security-Policy"]),
                         (200, "image/webp", "sandbox"))
        self.assertEqual(Image.open(io.BytesIO(b"".join(tile.streaming_content))).size, (2050, 300))
        self.assertEqual(self.client.get(reverse("maps:plan_tile", args=[plan.pk, 3])).status_code, 404)
        # Rendered anew (here: cropped to the left half), the old tiles go and the plan stays where it is.
        old = [tile["name"] for tile in plan.tiles]
        from .. import plans
        with self.captureOnCommitCallbacks(execute=True):
            plan.crop = [0, 0, 0.5, 1]
            plans.save(plan)
        self.assertEqual(len(plan.tiles), 2)
        self.assertFalse(any(plan.image.storage.exists(name) for name in old))
        self.assertLess(plan.residual_m, 0.01)

    def test_a_level_has_several_plans(self):
        # One per house (WH-1 and HH-1 share level -1), or several sheets; and one of a stacked part only.
        points = [{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                  {"pixel": [400, 0], "lonlat": list(local_point(8, 0).coords)}]
        first = self.plan(name="WH", control_points=points)
        second = self.plan(name="HH", control_points=points)
        part = self.plan(name="HBB.2", location=self.upper, control_points=points)
        older = self.plan(name="2019", shown=False, control_points=points)  # selectable, hidden at first
        self.plan(name="1990", active=False, control_points=points)  # not offered
        first.refresh_from_db()
        self.assertTrue(first.active and second.active and part.active)
        data = self.client.get(reverse("maps:level_data", args=[-1])).json()
        self.assertEqual({plan["name"]: (plan["location"], plan["shown"]) for plan in data["plans"]},
                         {"WH": (None, True), "HH": (None, True), "HBB.2": (self.upper.pk, True), "2019": (None, False)})
        self.client.force_login(self.staff)
        self.client.post(reverse("maps:plan_align", args=[older.pk]),
                         {"action": "settings", "opacity": "0.8", "active": "1", "shown": "1"})
        older.refresh_from_db()
        self.assertTrue(older.shown)
        self.assertEqual(self.client.get(reverse("maps:level_data", args=[0])).json()["plans"], [])

    def test_a_plan_of_a_stacked_part_is_on_its_level(self):
        plan = FloorPlan(level=0, location=self.upper)
        with self.assertRaises(ValidationError):
            plan.clean()
        plan.level = -1
        plan.clean()

    def test_the_upload_offers_the_levels_and_stacked_parts(self):
        self.client.force_login(self.staff)
        form = self.client.get(reverse("maps:plans")).context["form"]
        self.assertEqual(form.fields["level"].choices, [(-1, "-1 (HH-1, WH-1)")])
        self.assertEqual(list(form.fields["location"].queryset), [self.lower, self.upper])


@unittest.skipUnless(render.pdftoppm(), "poppler (pdftoppm) is not installed")
class PdfTests(TestCase):
    def test_a_pdf_page_without_its_annotations(self):
        # A one-page PDF with a red square annotation; rendered, the page stays white.
        pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
               b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Annots[4 0 R]>>endobj\n"
               b"4 0 obj<</Type/Annot/Subtype/Square/Rect[10 10 190 90]/C[1 0 0]/IC[1 0 0]/T(Someone)"
               b"/AP<</N 5 0 R>>>>endobj\n"
               b"5 0 obj<</Type/XObject/Subtype/Form/BBox[0 0 180 80]/Length 26>>stream\n"
               b"1 0 0 rg 0 0 180 80 re f\n\nendstream endobj\n"
               b"trailer<</Root 1 0 R>>\n%%EOF")
        rendered, width, height = render.render(io.BytesIO(pdf), suffix=".pdf", dpi=72)
        self.assertEqual((width, height), (200, 100))
        self.assertEqual(rendered.convert("RGB").getpixel((100, 50)), (255, 255, 255))
        image = Image.open(io.BytesIO(render.webp(rendered, "plan.webp").read()))
        self.assertEqual(image.format, "WEBP")
        self.assertNotIn("exif", image.info)
