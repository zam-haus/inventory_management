from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .. import search
from ..models import Category, Item, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit, UniqueItem
from .test_documents_and_photos import MediaMixin, png


@override_settings(LANGUAGE_CODE="en")
class ResultListTests(MediaMixin, TestCase):
    """The lists of the location, item and category pages are result rows, as the search shows them
    (results/entries.html, docs/search.md)."""

    @classmethod
    def setUpTestData(cls):
        MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        shelf = LocationType.objects.create(name="Shelf", moveable=True, category=LocationType.Category.STORAGE_UNIT)
        cls.room = Location.objects.create(type=room, name="Store", short_name="ST")
        cls.other = Location.objects.create(type=room, name="Workshop", short_name="WS")
        cls.shelf = Location.objects.create(type=shelf, name="Shelf 1", short_name="S1", parent_location=cls.room)
        cls.glue = Item.objects.create(name="Glue", description="Wood glue", measurement_unit_id=1)
        ItemLocation.objects.create(item=cls.glue, location=cls.room, amount=3)
        ItemLocation.objects.create(item=cls.glue, location=cls.other, amount=1)
        cls.drill = Item.objects.create(name="Drill", kind=Item.Kind.UNIQUE, measurement_unit_id=1)
        cls.blue = UniqueItem.objects.create(item=cls.drill, name="blue", location=cls.room, notes="Spare battery")
        cls.red = UniqueItem.objects.create(item=cls.drill, name="red", location=cls.other)
        cls.member = get_user_model().objects.create_user("member")
        cls.member.user_permissions.add(Permission.objects.get(codename="change_stock"))

    def test_the_location_page_lists_result_rows(self):
        self.client.force_login(self.member)
        content = self.client.get(self.room.get_absolute_url()).content.decode()
        self.assertEqual(content.count("data-result-list"), 3)  # items, unique items, sub-locations
        items = content[content.index('id="location-items"'):content.index('id="location-unique-items"')]
        # The item's other places, not this one; the amount here and the stock button in the row.
        self.assertIn(f'href="{self.other.get_absolute_url()}">Workshop</a>', items)
        self.assertNotIn(f'class="result-place" href="{self.room.get_absolute_url()}"', items)
        row = items[items.index('data-result-entry'):]
        self.assertLess(row.index("3 pc"), row.index("stock-change-button"))
        self.assertIn("Wood glue", items)
        unique = content[content.index('id="location-unique-items"'):]
        self.assertIn('<span class="result-subtitle">blue</span>', unique)
        self.assertIn("Spare battery", unique)
        self.assertNotIn(f'class="result-place" href="{self.room.get_absolute_url()}"', unique)
        # A sub-location without the path above it: that is this page.
        shelf = content[content.index(f'href="{self.shelf.get_absolute_url()}"'):]
        self.assertNotIn("bi-geo-alt", shelf[:shelf.index("</li>")])

    def test_locations_show_what_is_in_them(self):
        # As in the location tree: sub-locations by kind in the whole subtree, items and unique items right there.
        box = LocationType.objects.create(name="Box", moveable=True, category=LocationType.Category.CONTAINER)
        Location.objects.create(type=box, name="Box", short_name="B1", parent_location=self.shelf)
        Location.objects.create(type=box, name="Old box", short_name="B2", parent_location=self.shelf, is_deleted=True)
        ItemLocation.objects.create(item=self.glue, location=self.shelf, amount=1)
        room, shelf = search.render.listed("location", [self.room, self.shelf])
        self.assertEqual([(tally.icon, tally.number, tally.text) for tally in room.counts], [
            ("bookshelf", 1, "1 storage unit"), ("eurobox-open", 1, "1 container"), ("boxes", 1, "1 item"),
            ("box-star", 1, "1 unique item")])
        self.assertEqual([(tally.icon, tally.number) for tally in shelf.counts], [("eurobox-open", 1), ("boxes", 1)])
        content = self.client.get(self.room.get_absolute_url()).content.decode()
        row = content[content.index(f'class="result-link" href="{self.shelf.get_absolute_url()}"'):]
        self.assertIn('<span class="result-count" title="1 container">', row[:row.index("</li>")])

    def test_the_item_page_lists_result_rows(self):
        page = self.client.get(self.glue.get_absolute_url(), {"loc": self.other.pk}).content.decode()
        self.assertEqual(page.count('class="result-entry'), 2)
        self.assertIn('class="result-entry result-entry-current" data-result-entry aria-current="location"', page)
        unique = self.client.get(self.drill.get_absolute_url()).content.decode()
        self.assertIn(f'href="{self.blue.get_absolute_url()}"', unique)
        self.assertIn(f'class="result-place" href="{self.other.get_absolute_url()}"', unique)

    def test_photos_open_below_the_row(self):
        ItemImage.objects.create(item=self.glue, image=png("red"), description="Bottle")
        content = self.client.get(self.room.get_absolute_url()).content.decode()
        self.assertIn('data-result-photos aria-expanded="false"', content)
        self.assertIn("&quot;alt&quot;: &quot;Bottle&quot;", content)
        self.assertIn('id="result-viewer"', content)  # base.html, once per page

    def test_what_rows_need_comes_only_with_rows(self):
        # The icons drawn once, the photo viewer and results.js: on pages with rows, or that get them while typing.
        for url in (self.room.get_absolute_url(), reverse("index"), Category.objects.create(name="Empty").get_absolute_url()):
            with self.subTest(url=url):
                content = self.client.get(url).content.decode()
                self.assertEqual(content.count('id="result-viewer"'), 1)
                self.assertEqual(content.count('class="result-sprite"'), 1)
                self.assertIn("results.js", content)
        content = self.client.get(reverse("index_items")).content.decode()
        self.assertNotIn('id="result-viewer"', content)
        self.assertNotIn("results.js", content)

    def test_queries_do_not_grow_with_the_rows(self):
        tools = Category.objects.create(name="Tools")

        def queries(url):
            self.client.get(url)  # thumbnails made once
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(captured)

        def add(n):
            item = Item.objects.create(name=f"Clamp {n}", measurement_unit_id=1, category=tools)
            ItemLocation.objects.create(item=item, location=self.room, amount=n)
            ItemLocation.objects.create(item=item, location=self.other, amount=n)
            ItemImage.objects.create(item=item, image=png())
            Location.objects.create(type=self.shelf.type, name=f"Shelf {n + 2}", short_name=f"S{n + 2}",
                                    parent_location=self.room)
            unique = UniqueItem.objects.create(item=self.drill, location=self.room)
            ItemImage.objects.create(item=self.drill, unique_item=unique, image=png())
            ItemLocation.objects.create(item=self.glue, location=Location.objects.create(
                type=self.room.type, name=f"Room {n}", short_name=f"R{n}"), amount=1)

        add(0)
        urls = (self.room.get_absolute_url(), self.glue.get_absolute_url(), self.drill.get_absolute_url(),
                tools.get_absolute_url())
        before = {url: queries(url) for url in urls}
        for n in range(1, 10):
            add(n)
        self.assertEqual({url: queries(url) for url in urls}, before)
