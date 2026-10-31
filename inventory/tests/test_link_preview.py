"""The OpenGraph tags of shared links (inventory/link_preview.py, docs/link-previews.md)."""
import re
import shutil
import tempfile
from html import unescape
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from ..models import Category, ItemImage, Location, UniqueItem
from ..label_ids.testing import SETTINGS, InventoryFixture
from .test_unique_items import UniqueItemFixture


def photo(name="photo.png"):
    content = BytesIO()
    Image.new("RGB", (800, 600), "green").save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


class MetaTags:
    def tags(self, url):
        """The page's meta tags by property or name, as a dict (each appears once)."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        head = response.content.decode().split("</head>")[0]
        found = {}
        for match in re.finditer(r'<meta (?:property|name)="([^"]+)" content="([^"]*)">', head):
            self.assertNotIn(match[1], found)
            found[match[1]] = unescape(match[2])
        return found

    def setUp(self):
        super().setUp()
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)


@override_settings(**SETTINGS)
class LinkPreviewTests(MetaTags, InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.tools = Category.objects.create(name="Test tools", description="Tools to try things.\nNot here: toys")
        cls.drills = Category.objects.create(name="Test drills", parent_category=cls.tools)
        cls.item.category = cls.drills
        cls.item.description = "For **wood** & metal, with [two batteries](https://example.org).\n\n" + "More. " * 60
        cls.item.save()
        cls.shelf = Location.objects.create(name="Shelf", short_name="S", type=cls.kind, parent_location=cls.location,
                                            physical_description="Steel, *five* boards")

    def test_item_with_a_photo(self):
        ItemImage.objects.create(item=self.item, image=photo("receipt-2026-private.png"))
        tags = self.tags(self.item.get_absolute_url())
        self.assertEqual(tags["og:title"], "Drill")
        self.assertTrue(tags["og:description"].startswith("For wood & metal, with two batteries. More."))
        self.assertLessEqual(len(tags["og:description"]), 200)
        self.assertEqual(tags["description"], tags["og:description"])
        self.assertEqual(tags["og:url"], f"https://inv.zam.haus{self.item.get_absolute_url()}")
        # The thumbnail, not the original with its name.
        self.assertTrue(tags["og:image"].startswith("https://inv.zam.haus/media/cache/"), tags["og:image"])
        self.assertNotIn("receipt", tags["og:image"])
        self.assertEqual((tags["og:image:width"], tags["og:image:height"]), ("640", "480"))
        self.assertEqual(tags["twitter:card"], "summary_large_image")
        self.assertEqual(tags["og:site_name"], "ZAM inventory")
        self.assertEqual(tags["og:locale"], "en")

    def test_a_photo_whose_file_is_missing_gives_the_logo(self):
        image = ItemImage.objects.create(item=self.item, image=photo())
        image.image.storage.delete(image.image.name)
        tags = self.tags(self.item.get_absolute_url())
        self.assertIn("icon-maskable-512.png", tags["og:image"])
        self.assertEqual(tags["twitter:card"], "summary")

    def test_item_without_photo_or_description_has_its_category_and_the_logo(self):
        tags = self.tags(self.other_item.get_absolute_url())
        self.assertEqual(tags["og:title"], "Saw")
        self.assertNotIn("og:description", tags)
        self.other_item.category = self.drills
        self.other_item.save()
        tags = self.tags(self.other_item.get_absolute_url())
        self.assertEqual(tags["og:description"], "Test tools/Test drills")
        self.assertRegex(tags["og:image"], r"^https://inv\.zam\.haus/static/inventory/favicon/(dev/)?icon-maskable-512\.png")
        self.assertEqual(tags["twitter:card"], "summary")

    def test_location_has_its_path_and_overview_photo(self):
        tags = self.tags(self.shelf.get_absolute_url())
        self.assertEqual(tags["og:title"], f"Shelf · {self.shelf.unique_identifier}")
        self.assertEqual(tags["og:description"], "Workshop. Steel, five boards")
        self.assertEqual(tags["twitter:card"], "summary")
        self.shelf.overview_photo = photo()
        self.shelf.save()
        tags = self.tags(self.shelf.get_absolute_url())
        self.assertTrue(tags["og:image"].startswith("https://inv.zam.haus/media/cache/"))

    def test_category_has_its_first_line_only(self):
        tags = self.tags(self.tools.get_absolute_url())
        self.assertEqual(tags["og:title"], "Test tools")
        self.assertEqual(tags["og:description"], "Tools to try things.")
        self.assertEqual(self.tags(self.drills.get_absolute_url())["og:description"], "Test tools/Test drills")

    def test_other_pages_have_the_general_tags(self):
        tags = self.tags("/?q=drill")
        self.assertNotIn("og:title", tags)  # bots take the <title>
        self.assertNotIn("og:description", tags)
        self.assertEqual(tags["og:url"], "https://inv.zam.haus/?q=drill")
        self.assertEqual(tags["twitter:card"], "summary")

    def test_item_page_needs_at_most_one_more_query(self):
        url = self.item.get_absolute_url()
        self.client.get(url)
        with CaptureQueriesContext(connection) as with_preview:
            self.client.get(url)
        from .. import link_preview
        original = link_preview.for_item
        link_preview.for_item = lambda item: link_preview.Preview()
        self.addCleanup(setattr, link_preview, "for_item", original)
        with CaptureQueriesContext(connection) as without:
            self.client.get(url)
        self.assertLessEqual(len(with_preview), len(without) + 1)


@override_settings(**SETTINGS)
class UniqueItemPreviewTests(MetaTags, UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.extinguisher.description = "Foam, 6 litres."
        cls.extinguisher.procurement_source = "Shop of Robin"
        cls.extinguisher.save()
        cls.unique_item.responsible_team = cls.team
        cls.unique_item.responsible_user = cls.member
        cls.unique_item.owner_user = cls.owner
        cls.unique_item.notes = "Lent to Alex until Friday"
        cls.unique_item.procurement_source = "Flea market"
        cls.unique_item.save()

    def test_nothing_about_people(self):
        tags = self.tags(self.unique_item.get_absolute_url())
        self.assertEqual(tags["og:title"], "Fire extinguisher K7R-4XD")
        self.assertEqual(tags["og:description"], "Foam, 6 litres.")
        text = " ".join(tags.values())
        for private in ("Woodworking", "Alex", "Robin", "Lent", "Flea", "Shop"):
            self.assertNotIn(private, text)

    def test_own_photo_first(self):
        ItemImage.objects.create(item=self.extinguisher, image=photo("general.png"))
        general = self.tags(self.unique_item.get_absolute_url())["og:image"]
        ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item, image=photo("own.png"))
        own = self.tags(self.unique_item.get_absolute_url())["og:image"]
        self.assertNotEqual(own, general)
        self.assertTrue(own.startswith("https://inv.zam.haus/media/cache/"))

    def test_disposed_says_so_without_why(self):
        UniqueItem.objects.filter(pk=self.unique_item.pk).update(
            disposed_at=timezone.now(), disposal_note="Broken by Alex", location=None)
        tags = self.tags(self.unique_item.get_absolute_url())
        self.assertEqual(tags["og:description"], "Disposed. Foam, 6 litres.")
        self.assertNotIn("Broken", " ".join(tags.values()))
