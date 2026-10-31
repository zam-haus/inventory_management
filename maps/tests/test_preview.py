"""Link previews of the map (maps/preview.py, docs/link-previews.md)."""
import io
import re
import shutil
import tempfile
from datetime import timedelta
from html import unescape
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inventory.models import Location

from .. import geo, positions, preview
from ..models import FloorPlan, LocationShape
from ..views import level_payload
from .test_geo import CENTER, local_point
from .test_positions import Building


def png(width=400, height=300, colour=(30, 160, 30)):
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, "PNG")
    return out.getvalue()


@override_settings(LANGUAGE_CODE="en", DEFAULT_URL="https://inv.zam.haus")
class PreviewTests(Building, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        # A green plan of 40 × 30 m with its top left corner at CENTER; the store LAG on it, the pallet in HBB.2.
        from .. import plans
        plan = FloorPlan(level=-1, control_points=[{"pixel": [0, 0], "lonlat": list(CENTER.coords)},
                                                   {"pixel": [400, 0], "lonlat": list(local_point(40, 0).coords)}])
        plan.source.save("plan.png", SimpleUploadedFile("plan.png", png()), save=False)
        self.plan = plans.save(plan)
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(10, -10), 8, 6))
        positions.set_location_shape(self.pallet, None, local_point(30, -20))

    def tags(self, url):
        head = self.client.get(url).content.decode().split("</head>")[0]
        return {m[1]: unescape(m[2]) for m in re.finditer(r'<meta (?:property|name)="([^"]+)" content="([^"]*)">', head)}

    def picture(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("max-age=86400", response["Cache-Control"])
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        self.assertEqual(image.size, (1200, 630))
        return image

    def kept(self):
        storage = FloorPlan._meta.get_field("image").storage
        return sorted(storage.listdir("map_previews/-1")[1]) if storage.exists("map_previews/-1") else []

    def test_a_location_on_the_map(self):
        tags = self.tags(f"/map/-1/?p=loc:{self.pallet.pk}")
        self.assertEqual(tags["og:title"], self.pallet.title_with_code)
        self.assertEqual(tags["og:description"], "Werkhaus -1 › Holzbaubühne › oben, on the map of level -1")
        self.assertEqual(tags["og:url"], f"https://inv.zam.haus/map/-1/?p=loc:{self.pallet.pk}")
        self.assertEqual(tags["og:image"], f"https://inv.zam.haus/map/level/-1/preview.png?p=loc:{self.pallet.pk}")
        self.assertEqual((tags["og:image:width"], tags["og:image:height"]), ("1200", "630"))
        self.assertEqual(tags["twitter:card"], "summary_large_image")
        image = self.picture(tags["og:image"].removeprefix("https://inv.zam.haus"))
        # Centred on the pallet, highlighted (pink) on the green plan.
        self.assertGreater(sum(1 for pixel in image.getdata() if pixel[0] > 180 and pixel[1] < 120), 500)
        self.assertGreater(sum(1 for pixel in image.getdata() if pixel[1] > pixel[0] + 60), 100000)

    def test_a_marked_point_names_the_room(self):
        point = local_point(10, -10)
        tags = self.tags(f"/map/-1/?m={point.y},{point.x}&t=Meet%20here")
        self.assertEqual(tags["og:title"], "Meet here")
        self.assertEqual(tags["og:description"], f"Marked point in {self.store.title_with_code}, level -1")
        self.assertIn("preview.png?m=", tags["og:image"])
        self.assertIn("&t=Meet%20here", tags["og:image"])
        self.picture(tags["og:image"].removeprefix("https://inv.zam.haus"))
        self.assertEqual(self.kept(), [])  # marks are drawn on each request only

    def test_a_marked_area_has_its_size(self):
        corners = [local_point(0, -1), local_point(4, -1), local_point(4, -4), local_point(0, -4)]
        query = ";".join(f"{c.y},{c.x}" for c in corners)
        tags = self.tags(f"/map/-1/?a={query}")
        self.assertEqual(tags["og:title"], "Marked area")
        self.assertEqual(tags["og:description"], "Marked area on level -1, about 12 m²")
        self.picture(tags["og:image"].removeprefix("https://inv.zam.haus"))

    def test_what_is_not_on_the_level_shows_the_level(self):
        far = local_point(5000, 0)
        for query in (f"m={far.y},{far.x}", "m=1,nan", "m=x", "a=1,2;3,4", f"p=loc:{self.other_level.pk}", "p=loc:x"):
            tags = self.tags(f"/map/-1/?{query}")
            self.assertNotIn("og:title", tags, query)
            self.assertEqual(tags["og:image"], "https://inv.zam.haus/map/level/-1/preview.png", query)

    def test_the_level_without_a_target(self):
        with CaptureQueriesContext(connection) as plain:
            tags = self.tags("/map/-1/")
        self.assertNotIn("og:title", tags)  # bots take the <title>: "Map, level -1"
        self.assertEqual(tags["og:image"], "https://inv.zam.haus/map/level/-1/preview.png")
        self.assertEqual(tags["og:image:alt"], "Map, level -1")
        self.assertFalse(any("maps_floorplan" in query["sql"] for query in plain.captured_queries))
        self.picture("/map/level/-1/preview.png")
        self.assertEqual(self.client.get("/map/level/5/preview.png").status_code, 404)

    def test_kept_pictures_are_replaced_and_swept(self):
        url = f"/map/level/-1/preview.png?p=loc:{self.store.pk}"
        self.picture(url)
        first = self.kept()
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].startswith(f"loc-{self.store.pk}-"))
        with mock.patch.object(preview, "render") as drawn:
            self.picture(url)  # kept
        drawn.assert_not_called()
        positions.set_location_shape(self.store, LocationShape.Kind.AREA, geo.rectangle(local_point(12, -10), 8, 6))
        self.picture(url)
        second = self.kept()
        self.assertEqual(len(second), 1)  # the older one went
        self.assertNotEqual(second, first)
        self.picture("/map/level/-1/preview.png")
        self.assertEqual(len(self.kept()), 2)
        # The location deleted: its picture goes with the next sweep (once a day).
        Location.objects.filter(pk=self.store.pk).update(is_deleted=True)
        preview.sweep()
        self.assertEqual(len(self.kept()), 2)  # swept just now
        preview.sweep(now=timezone.now() + timedelta(days=2))
        self.assertEqual([name.split("-")[0] for name in self.kept()], ["level"])
        preview.sweep(now=timezone.now() + timedelta(days=100))
        self.assertEqual(self.kept(), [])

    def test_a_level_with_nothing_shows_the_logo(self):
        payload = level_payload(-1)
        payload["plans"], payload["features"]["features"] = [], []
        self.assertIsNone(preview.render(payload, preview.Target()))

    def test_map_links_keep_the_target_in_the_query(self):
        page = self.client.get(reverse("view_unique_item", args=[self.saw.pk])).content.decode()
        self.assertIn(f'href="/map/-1/?p=loc:{self.pallet.pk}"', page)
