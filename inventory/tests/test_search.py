from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .. import public_export, search
from ..change_log import TRACKED
from ..label_ids import services
from ..label_ids.testing import SETTINGS, make_id
from ..models import (Category, Item, ItemBarcode, ItemFile, ItemImage, ItemLocation, Location,
                      LocationType, MeasurementUnit, UniqueItem)
from ..search.fields import WANTED, searchable
from .test_documents_and_photos import MediaMixin, png

# Invented names only. Words in internal fields that the search must never find:
SECRETS = ("Xylopreis", "Xylokontakt", "Xylovorname", "Xylorechnung", "Xylokonto", "xylo@example.org")


def found(query):
    """(kind, title) of the hits, in their order."""
    hits = search.search(query).hits
    return [(entry.kind, entry.title) for entry in search.render.entries(hits)]


@override_settings(**SETTINGS)
class SearchTests(MediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        # The category tree the migrations bring would add hits of its own (CategorySearchTests has its own).
        Category.objects.all().delete()
        unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        shelf = LocationType.objects.create(name="Shelf", moveable=True)
        cls.wood = Location.objects.create(type=room, name="Holzwerkstatt", short_name="HW")
        cls.rack = Location.objects.create(type=shelf, name="Regal 3", short_name="R3", parent_location=cls.wood)
        cls.metal = Location.objects.create(type=room, name="Metallwerkstatt", short_name="MW")
        tools = Category.objects.create(name="Handwerkzeug")
        cls.screwdriver = Item.objects.create(name="Schraubendreher", measurement_unit=unit, category=tools)
        ItemLocation.objects.create(item=cls.screwdriver, location=cls.rack, amount=5)
        ItemLocation.objects.create(item=cls.screwdriver, location=cls.metal, amount=2)
        cls.drill = Item.objects.create(name="Bohrer", description="Spiralbohrer fuer Holz", measurement_unit=unit,
                                        last_purchase_price=Decimal("12.34"))
        ItemLocation.objects.create(item=cls.drill, location=cls.metal, amount=10)
        ItemBarcode.objects.create(item=cls.drill, data="4006381333931")
        cls.cordless = Item.objects.create(name="Akkuschrauber", kind=Item.Kind.UNIQUE, measurement_unit=unit)
        owner = get_user_model().objects.create_user(
            "xylokonto", email="xylo@example.org", first_name="Xylokonto", last_name="Xylokonto")
        cls.unique = UniqueItem.objects.create(
            item=cls.cordless, location=cls.wood, name="blau", notes="Ersatzakku im Koffer",
            purchase_price=Decimal("99.00"), owner_contact="Xylokontakt", owner_first_name="Xylovorname",
            owner_user=owner, responsible_user=owner)
        cls.label = services.claim(make_id("K7R4X").code, cls.unique, None)

    def test_one_list_of_locations_items_and_unique_items(self):
        self.assertEqual(found("akku"), [("item", "Akkuschrauber"), ("unique", "Akkuschrauber")])
        self.assertEqual(found("regal"), [("location", "Regal 3")])
        self.assertIn(("item", "Schraubendreher"), found("schraubendreher"))

    def test_hits_on_names_come_first(self):
        # The workshop by its name, then the drill by its description.
        self.assertEqual(found("holz"), [("location", "Holzwerkstatt"), ("item", "Bohrer")])

    def test_words_may_match_where_it_is_but_one_the_entry_itself(self):
        self.assertEqual(found("schraubendreher holzwerkstatt"), [("item", "Schraubendreher")])
        self.assertEqual(found("akkuschrauber blau holzwerkstatt"), [("unique", "Akkuschrauber")])
        self.assertEqual(found("werkstatt regal"), [("location", "Regal 3")])
        # A room alone finds the room, not everything stored in it.
        self.assertEqual(found("holzwerkstatt"), [("location", "Holzwerkstatt")])
        self.assertEqual(found("schraubendreher kueche"), [])

    def test_where_the_words_were_found(self):
        ItemImage.objects.create(item=self.drill, image=png(), description="Packung", ocr_text="HSS 6mm DIN 338")
        ItemFile.objects.create(item=self.drill, description="Datenblatt", file=ContentFile(b"%PDF", name="d.pdf"))
        cases = {"spiralbohrer": "description", "4006381": "barcode", "packung": "photo",
                 "din 338": "photo_text", "datenblatt": "file", "handwerkzeug": "category"}
        for query, source in cases.items():
            with self.subTest(query=query):
                hits = [hit for hit in search.search(query).hits if hit.kind != "category"]  # Handwerkzeug itself
                self.assertEqual([hit.sources for hit in hits], [(source,)])
        self.assertEqual(search.search("ersatzakku").hits[0].sources, ("notes",))
        self.assertEqual(search.search("schraubendreher").hits[0].sources, ())  # the name shows it anyway
        response = self.client.get(reverse("index"), {"q": "din 338"})
        self.assertContains(response, "Found in text on a photo")

    def test_internal_information_is_never_found(self):
        ItemFile.objects.create(item=self.cordless, unique_item=self.unique, description="Xylorechnung",
                                internal=True, file=ContentFile(b"%PDF", name="r.pdf"))
        for secret in (*SECRETS, "12.34", "99.00"):
            with self.subTest(secret=secret):
                self.assertEqual(found(secret), [])

    def test_the_rules_of_the_public_export_decide(self):
        for label, names in WANTED.items():
            for name in names:
                with self.subTest(field=f"{label}.{name}"):
                    self.assertTrue(public_export.publishable(label, name))
        replaced = {**public_export.EXPORTED_MODELS["inventory.item"]}
        replaced["replace"] = {**replaced["replace"], "description": public_export.emptied}
        with mock.patch.dict(public_export.EXPORTED_MODELS, {"inventory.item": replaced}):
            self.assertFalse(searchable(Item, "description"))
            self.assertEqual(found("spiralbohrer"), [])
        with mock.patch.dict(public_export.EXPORTED_MODELS, {"inventory.itemfile": {"filter": {"pk": None}}}):
            ItemFile.objects.create(item=self.drill, description="Datenblatt", file=ContentFile(b"%PDF", name="d.pdf"))
            self.assertEqual(found("datenblatt"), [])

    def test_internal_fields_of_the_change_log_are_replaced_in_the_export(self):
        for name, (_fields, internal) in TRACKED.items():
            replaced = set(public_export.EXPORTED_MODELS.get(f"inventory.{name}", {}).get("replace", {}))
            self.assertLessEqual(internal, replaced, name)

    def test_gone_entries_are_not_found(self):
        old = UniqueItem.objects.create(item=self.cordless, location=self.metal, name="alt")
        ItemImage.objects.create(item=self.cordless, unique_item=old, image=png(), ocr_text="Seriennummer 4711")
        old.disposed_at, old.location = timezone.now(), None
        old.save()
        self.assertEqual(found("4711"), [])
        self.assertEqual(found("akkuschrauber alt"), [])
        self.drill.delete()
        self.assertEqual(found("bohrer"), [])
        Location.objects.create(type=self.wood.type, name="Lager", short_name="LG", is_reserved=True)
        self.assertEqual(found("lager"), [])

    def test_words_are_marked_and_text_is_escaped(self):
        Item.objects.create(name="<script>alert(1)</script> Bohrmaschine", measurement_unit_id=1)
        response = self.client.get(reverse("index"), {"q": "bohrmaschine"})
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt; <mark>Bohrmaschine</mark>")
        self.assertNotContains(response, "<script>alert(1)")

    def test_entries_show_where_they_are(self):
        content = self.client.get(reverse("index"), {"q": "schraubendreher"}).content.decode()
        # The places are links of their own (the window in brief, location_info.js); the text stays selectable.
        self.assertIn(f'5 pc · <a class="result-place" href="{self.rack.get_absolute_url()}">Regal 3</a>', content)
        self.assertIn(f'2 pc · <a class="result-place" href="{self.metal.get_absolute_url()}">Metallwerkstatt</a>', content)
        self.assertNotIn('<a class="result-entry"', content)
        content = self.client.get(reverse("index"), {"q": "regal"}).content.decode()
        self.assertIn("Holzwerkstatt [HW]", content)  # the path above

    def test_unique_items_lead_there_directly(self):
        content = self.client.get(reverse("index"), {"q": "akkuschrauber"}).content.decode()
        # Named as everywhere: the item, its own name if any, its label ID.
        self.assertIn(f'<a href="{self.unique.get_absolute_url()}">Akkuschrauber blau '
                      '<span class="unique-item-code">K7R-4XD</span>'
                      '</a> · ', content)
        # Its own result carries the label ID after the name; its place line only the location.
        heading = content[content.index(f'<a class="result-link" href="{self.unique.get_absolute_url()}">'):]
        heading = heading[:heading.index("</a>")]
        self.assertIn('<span class="unique-item-code">K7R-4XD</span>', heading)

    def test_the_kind_on_photos(self):
        ItemImage.objects.create(item=self.drill, image=png(), description="Packung")
        content = self.client.get(reverse("index"), {"q": "bohrer"}).content.decode()
        self.assertIn('<span class="result-kind" aria-hidden="true"><svg', content)
        self.assertIn('class="bi bi-boxes"', content[content.index('class="result-kind"'):])

    def test_part_of_a_label_id(self):
        for part in ("K7R", "k7r-4", "7R4X"):
            with self.subTest(part=part):
                hits = search.search(part).hits
                self.assertEqual([(hit.kind, hit.pk, hit.sources) for hit in hits], [("unique", self.unique.pk, ("label",))])
        self.assertEqual(search.search("K7").hits, [])  # from three symbols on
        response = self.client.get(reverse("index"), {"q": "K7R"})
        self.assertContains(response, "Found in ZAMid")

    def test_codes(self):
        response = self.client.get(reverse("index"), {"q": self.label.code})
        self.assertRedirects(response, f"/id/{self.label.code}?via=webform", fetch_redirect_response=False)
        response = self.client.get(reverse("index"), {"q": self.label.code, "partial": "1"})
        self.assertContains(response, f'href="/id/{self.label.code}?via=webform"')
        # A location's code leads to it, too; while typing, it is offered as a link.
        self.assertRedirects(self.client.get(reverse("index"), {"q": "hw"}), self.wood.get_absolute_url(),
                             fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("index"), {"q": "hw", "partial": "1"}),
                            f'href="{self.wood.get_absolute_url()}"')
        self.assertEqual(found("hw"), [("location", "Holzwerkstatt"), ("location", "Regal 3")])  # HW, then HW.R3
        self.assertEqual(found("r3"), [("location", "Regal 3")])

    def test_codes_from_their_start(self):
        rack = LocationType.objects.create(name="Numbered rack", unique=True)
        compartment = LocationType.objects.create(name="Compartment")
        r006 = Location.objects.create(type=rack, name="Regal 6", short_name="R006")
        for code in ("b", "a"):
            Location.objects.create(type=compartment, name=f"Fach {code}", short_name=code, parent_location=r006)
        Location.objects.create(type=rack, name="Regal 5", short_name="R005")
        Location.objects.create(type=rack, name="Regal 10", short_name="R010")
        codes = lambda query: [entry.code for entry in search.render.entries(search.search(query).hits)
                               if entry.kind == "location"]
        # The location with exactly that code first, then those below it.
        self.assertEqual(codes("r006"), ["R006", "R006.a", "R006.b"])
        self.assertEqual(sorted(codes("R00")), ["R005", "R006", "R006.a", "R006.b"])
        self.assertEqual(codes("hw.r3"), ["HW.R3"])
        # Typed and sent, the code opens its location; while typing it is offered, above the results.
        self.assertRedirects(self.client.get(reverse("index"), {"q": "R006"}), r006.get_absolute_url(),
                             fetch_redirect_response=False)
        partial = self.client.get(reverse("index"), {"q": "R006", "partial": "1"})
        self.assertContains(partial, f'href="{r006.get_absolute_url()}"')
        self.assertEqual([entry.code for entry in partial.context["entries"]], ["R006", "R006.a", "R006.b"])

    def test_partial_is_only_the_results(self):
        content = self.client.get(reverse("index"), {"q": "bohrer", "partial": "1"}).content.decode()
        self.assertTrue(content.lstrip().startswith('<div class="search-results" data-status="1 result">'))
        self.assertNotIn("<nav", content)

    def test_empty_search(self):
        with mock.patch.object(search.contains, "search") as searched:
            response = self.client.get(reverse("index"))
        searched.assert_not_called()
        self.assertContains(response, 'name="q" value=""')
        self.assertNotContains(response, "Nothing found.")

    def test_further_pages(self):
        Item.objects.bulk_create([Item(name=f"Zwinge {n:03}", measurement_unit_id=1) for n in range(search.PAGE + 5)])
        Location.objects.create(type=self.wood.type, name="Zwingenlager", short_name="SL")
        first = search.search("zwinge")
        self.assertEqual((len(first.hits), first.next_offset), (search.PAGE, search.PAGE))
        second = search.search("zwinge", first.next_offset)
        self.assertEqual((len(second.hits), second.next_offset), (6, None))
        # Every hit once, the location (a hit on its name, too) first.
        keys = [(hit.kind, hit.pk) for hit in first.hits + second.hits]
        self.assertEqual(len(set(keys)), search.PAGE + 6)
        self.assertEqual(keys[0][0], "location")
        names = [entry.title for entry in search.render.entries(first.hits + second.hits)][1:]
        self.assertEqual(names, sorted(names))
        url = reverse("index")
        content = self.client.get(url, {"q": "zwinge"}).content.decode()
        self.assertIn(f'data-result-next="{url}?q=zwinge&amp;offset={search.PAGE}"', content)
        self.assertIn('data-status="More than 50 results"', content)
        more = self.client.get(url, {"q": "zwinge", "offset": search.PAGE, "partial": "1"}).content.decode()
        self.assertTrue(more.lstrip().startswith("<template data-result-entries>"))
        self.assertEqual(more.count('class="result-entry"'), 6)
        self.assertNotIn("data-result-next", more)

    def test_at_most_max_results(self):
        with mock.patch.object(search, "MAX_RESULTS", 10), mock.patch.object(search, "PAGE", 6):
            Item.objects.bulk_create([Item(name=f"Mutter {n}", measurement_unit_id=1) for n in range(12)])
            last = search.search("mutter", 6)
            self.assertEqual((len(last.hits), last.next_offset, last.capped), (4, None, True))
            content = self.client.get(reverse("index"), {"q": "mutter", "offset": 6}).content.decode()
            self.assertIn("There are more results than shown.", content)

    def test_a_summary_by_kind_filters_the_results(self):
        result = search.search("akku")
        self.assertEqual(result.counts, {"item": 1, "unique": 1})
        only = search.search("akku", kinds={"unique"})
        self.assertEqual([hit.kind for hit in only.hits], ["unique"])
        self.assertEqual(only.counts, result.counts)  # the others are counted, too
        url = reverse("index")
        # None chosen: all shown, and a first click shows only that kind.
        response = self.client.get(url, {"q": "akku"})
        self.assertEqual([(f["kind"], f["text"], f["chosen"], f["url"]) for f in response.context["kind_filters"]], [
            ("item", "1 item", False, f"{url}?q=akku&kinds=item"),
            ("unique", "1 unique item", False, f"{url}?q=akku&kinds=unique")])
        self.assertContains(response, f'href="{url}?q=akku&amp;kinds=item" role="button" aria-pressed="false"')
        response = self.client.get(url, {"q": "akku", "kinds": "unique"})
        self.assertEqual([entry.kind for entry in response.context["entries"]], ["unique"])
        self.assertContains(response, '<input type="hidden" name="kinds" value="unique">')
        # Another click adds a kind; a click on the chosen one leaves it out again, none chosen shows all.
        self.assertEqual([(f["kind"], f["chosen"], f["url"]) for f in response.context["kind_filters"]], [
            ("item", False, f"{url}?q=akku&kinds=item,unique"), ("unique", True, f"{url}?q=akku")])
        both = self.client.get(url, {"q": "akku", "kinds": "item,unique"})
        self.assertEqual([(f["kind"], f["chosen"], f["url"]) for f in both.context["kind_filters"]], [
            ("item", True, f"{url}?q=akku&kinds=unique"), ("unique", True, f"{url}?q=akku&kinds=item")])
        # All chosen is the same as none.
        every = self.client.get(url, {"q": "akku", "kinds": "location,category,item,unique"})
        self.assertEqual([f["chosen"] for f in every.context["kind_filters"]], [False, False])
        self.assertEqual(len(every.context["entries"]), 2)
        # A chosen kind without hits stays, to leave it out again.
        none = self.client.get(url, {"q": "akkuschrauber blau", "kinds": "item"})  # only the unique item matches
        self.assertContains(none, "Only kinds not chosen above have results.")
        self.assertEqual([(f["kind"], f["chosen"]) for f in none.context["kind_filters"]],
                         [("item", True), ("unique", False)])
        # Unknown kinds are ignored; no hits, no summary.
        self.assertEqual(len(self.client.get(url, {"q": "akku", "kinds": "nonsense"}).context["entries"]), 2)
        self.assertEqual(self.client.get(url, {"q": "zzzz"}).context["kind_filters"], [])

    def test_further_pages_keep_the_kinds(self):
        Item.objects.bulk_create([Item(name=f"Zwinge {n}", measurement_unit_id=1) for n in range(search.PAGE + 6)])
        Location.objects.create(type=self.wood.type, name="Zwingenlager", short_name="ZL")
        url = reverse("index")
        response = self.client.get(url, {"q": "zwinge", "kinds": "item"})
        self.assertEqual({entry.kind for entry in response.context["entries"]}, {"item"})
        self.assertContains(response, f'data-result-next="{url}?q=zwinge&amp;kinds=item&amp;offset={search.PAGE}"')

    def test_counts_beyond_the_cap(self):
        with mock.patch.object(search, "MAX_RESULTS", 10), mock.patch.object(search, "PAGE", 6):
            Item.objects.bulk_create([Item(name=f"Mutter {n}", measurement_unit_id=1) for n in range(12)])
            filters = self.client.get(reverse("index"), {"q": "mutter"}).context["kind_filters"]
            self.assertEqual([f["text"] for f in filters], ["10+ items"])

    def test_photos_of_a_result(self):
        ItemImage.objects.create(item=self.drill, image=png("red"), description="Packung")
        old = UniqueItem.objects.create(item=self.cordless, location=self.metal, name="alt")
        of_unique = ItemImage.objects.create(item=self.cordless, unique_item=self.unique, image=png("blue"), is_primary=True)
        general = ItemImage.objects.create(item=self.cordless, image=png("green"))
        ItemImage.objects.create(item=self.cordless, unique_item=old, image=png("black"))
        old.disposed_at, old.location = timezone.now(), None
        old.save()
        entries = {entry.kind: entry for entry in search.render.entries(search.search("akkuschrauber").hits)}
        # The item: its own photos first, then those of its unique items still in the inventory.
        self.assertEqual([image.name for image, _ in entries["item"].photos], [general.image.name, of_unique.image.name])
        # A unique item: its own photos, then those of the item in general.
        self.assertEqual([image.name for image, _ in entries["unique"].photos], [of_unique.image.name, general.image.name])
        content = self.client.get(reverse("index"), {"q": "bohrer"}).content.decode()
        self.assertIn('aria-label="Show the photo of Bohrer"', content)
        self.assertIn('data-photos="[{&quot;src&quot;: &quot;/media/', content)
        self.assertIn("&quot;alt&quot;: &quot;Packung&quot;", content)

    def test_queries_do_not_grow_with_the_hits(self):
        for n in range(10):
            item = Item.objects.create(name=f"Zange {n}", measurement_unit_id=1)
            ItemLocation.objects.create(item=item, location=self.metal, amount=n)
            ItemImage.objects.create(item=item, image=png())
        url = reverse("index")
        self.client.get(url, {"q": "zange", "partial": "1"})  # thumbnails made once
        self.client.get(url, {"q": "zange 3", "partial": "1"})
        with CaptureQueriesContext(connection) as one:
            self.client.get(url, {"q": "zange 3", "partial": "1"})
        with CaptureQueriesContext(connection) as ten:
            self.client.get(url, {"q": "zange", "partial": "1"})
        self.assertEqual(len(one), len(ten))

    def test_icons_of_the_kinds(self):
        shelf_type = LocationType.objects.create(name="Shelf unit", category=LocationType.Category.STORAGE_UNIT)
        box_type = LocationType.objects.create(name="Euro box", category=LocationType.Category.CONTAINER)
        Location.objects.create(type=shelf_type, name="Werkbankregal", short_name="WR", parent_location=self.wood)
        Location.objects.create(type=box_type, name="Werkbankkiste", short_name="WK", parent_location=self.wood)
        icons = {entry.title: entry.icon for entry in search.render.entries(search.search("werkbank").hits)}
        self.assertEqual(icons, {"Werkbankregal": "bookshelf", "Werkbankkiste": "eurobox-open"})
        icons = {(entry.kind, entry.title): entry.icon for entry in search.render.entries(search.search("akku").hits)}
        # An item tracked as unique items: several of them.
        self.assertEqual(icons, {("item", "Akkuschrauber"): "box-star-stack", ("unique", "Akkuschrauber"): "box-star"})
        self.assertEqual(search.render.entries(search.search("bohrer").hits)[0].icon, "boxes")
        self.assertEqual(search.render.entries(search.search("holzwerkstatt").hits)[0].icon, "geo-alt")
        content = self.client.get(reverse("index"), {"q": "werkbank"}).content.decode()
        self.assertIn('class="bi bi-eurobox-open"', content)
        self.assertIn('class="bi bi-bookshelf"', content)

    def test_the_home_page_and_the_navbar(self):
        self.assertEqual(reverse("index"), "/")
        content = self.client.get("/", {"q": "bohrer"}).content.decode()
        self.assertIn('<form class="search-bar" method="get" action="/" role="search" data-live-search>', content)
        self.assertIn('name="q" value="bohrer"', content)
        self.assertIn('<h1 class="visually-hidden">Search</h1>', content)
        navbar = content[content.index("<nav"):content.index("</nav>")]
        self.assertIn('href="/" aria-label="Search" data-navbar-search aria-controls="navbar-search"', navbar)
        self.assertIn('<form class="navbar-search" id="navbar-search" method="get" action="/" role="search" hidden>', navbar)


@override_settings(**SETTINGS)
class CategorySearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Category.objects.all().delete()  # the migrated tree; this test has its own
        unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        cls.fixing = Category.objects.create(name="Befestigung")
        cls.screws = Category.objects.create(
            name="Holzschrauben", parent_category=cls.fixing, keywords="Spax, Spanplattenschraube",
            description="Selbstschneidend, für Spanplatten\nNicht hier: Maschinenschrauben (Metrisch)")
        cls.metric = Category.objects.create(name="Metrisch", parent_category=cls.fixing)
        cls.spax = Item.objects.create(name="Senkkopf 4x40", measurement_unit=unit, category=cls.screws)
        Item.objects.create(name="Senkkopf 5x60", measurement_unit=unit, category=cls.screws)
        Item.objects.create(name="Mutter M6", measurement_unit=unit, category=cls.metric)
        Item.objects.create(name="Weg", measurement_unit=unit, category=cls.screws, is_deleted=True)
        room = LocationType.objects.create(name="Room", unique=True)
        Location.objects.create(type=room, name="Holzlager", short_name="HL")

    def test_found_by_name_keyword_and_first_description_line(self):
        hit, = [hit for hit in search.search("holzschrauben").hits if hit.kind == "category"]
        self.assertEqual((hit.pk, hit.score, hit.sources), (self.screws.pk, 2, ()))
        hit, = search.search("spax").hits  # the keyword counts as name; no item is found by it
        self.assertEqual((hit.kind, hit.score, hit.sources, hit.snippets), (
            "category", 2, ("keywords",), {"keywords": "Spax"}))
        hit, = search.search("spanplatten").hits
        self.assertEqual((hit.pk, hit.score, hit.sources), (self.screws.pk, 2, ("keywords", "description")))
        hit, = search.search("selbstschneidend").hits
        self.assertEqual((hit.pk, hit.score, hit.sources), (self.screws.pk, 1, ("description",)))

    def test_not_found_by_what_belongs_elsewhere(self):
        self.assertEqual(found("maschinenschrauben"), [])

    def test_items_are_found_by_the_category_name_not_its_keywords(self):
        self.assertEqual(found("holzschrauben"), [
            ("category", "Holzschrauben"), ("item", "Senkkopf 4x40"), ("item", "Senkkopf 5x60")])
        self.assertEqual(found("spax"), [("category", "Holzschrauben")])

    def test_the_categories_above_are_its_path(self):
        self.assertEqual(found("befestigung spax"), [("category", "Holzschrauben")])
        # The category above alone finds only itself (and its items), not those below it.
        self.assertEqual([title for kind, title in found("befestigung") if kind == "category"], ["Befestigung"])

    def test_locations_come_first_then_categories_then_items(self):
        Item.objects.create(name="Holzschrauben Sortiment", measurement_unit_id=1)
        Location.objects.create(type=LocationType.objects.get(name="Room"), name="Holzschrauben", short_name="HS")
        self.assertEqual([kind for kind, _title in found("holzschrauben")][:3], ["location", "category", "item"])

    def test_the_entry(self):
        entry, = search.render.entries(search.search("spax").hits)
        self.assertEqual((entry.icon, entry.title, entry.where, entry.excerpt, entry.sources, entry.url),
                         ("folder", "Holzschrauben", "Befestigung", "Selbstschneidend, für Spanplatten",
                          ["keywords: Spax"], self.screws.get_absolute_url()))
        self.assertEqual([(tally.icon, tally.number, tally.text) for tally in entry.counts], [("boxes", 2, "2 items")])
        # As in the item tree: counted items and unique items, those below it, too.
        drill = Item.objects.create(name="Akkuschrauber", measurement_unit_id=1, category=self.metric,
                                    kind=Item.Kind.UNIQUE)
        UniqueItem.objects.create(item=drill, location=Location.objects.get(short_name="HL"))
        UniqueItem.objects.create(item=drill, disposed_at=timezone.now())
        befestigung = search.render.listed("category", [self.fixing])[0]
        self.assertEqual(befestigung.where, "")
        self.assertEqual([(tally.icon, tally.number) for tally in befestigung.counts], [("boxes", 3), ("box-star", 1)])
        content = self.client.get(reverse("index"), {"q": "spax"}).content.decode()
        self.assertIn('class="bi bi-folder"', content)
        self.assertIn("Found in keywords: Spax", content)
        self.assertIn('<span class="result-count" title="2 items">', content)

    def test_the_rules_of_the_public_export_decide(self):
        replaced = {**public_export.EXPORTED_MODELS["inventory.category"],
                    "replace": {"keywords": public_export.emptied}}
        with mock.patch.dict(public_export.EXPORTED_MODELS, {"inventory.category": replaced}):
            self.assertEqual(found("spax"), [])

    def test_within_a_category(self):
        lookalike = Category.objects.create(name="Befestigung alt")
        Item.objects.create(name="Senkkopf alt", measurement_unit_id=1, category=lookalike)
        hits = search.search("senkkopf", category=self.fixing).hits
        self.assertEqual({hit.pk for hit in hits}, set(Item.active.filter(category=self.screws).values_list("pk", flat=True)))
        self.assertEqual([(hit.kind, hit.pk) for hit in search.search("schrauben", category=self.fixing).hits],
                         [("category", self.screws.pk), ("item", self.spax.pk), ("item", self.spax.pk + 1)])
        # No locations, and not the category itself.
        self.assertEqual(search.search("holz befestigung", category=self.fixing).hits[0].pk, self.screws.pk)
        self.assertEqual(search.search("holzlager", category=self.fixing).hits, [])

    def test_the_summary_on_a_category_page(self):
        response = self.client.get(self.fixing.get_absolute_url(), {"q": "schrauben"})
        self.assertEqual([(f["kind"], f["text"]) for f in response.context["kind_filters"]],
                         [("category", "1 category"), ("item", "2 items")])
        items = self.client.get(self.fixing.get_absolute_url(), {"q": "schrauben", "kinds": "item", "partial": "1"})
        self.assertEqual({entry.kind for entry in items.context["entries"]}, {"item"})
        # Without words its list, without a summary.
        self.assertEqual(self.client.get(self.fixing.get_absolute_url()).context["kind_filters"], [])

    def test_queries_do_not_grow_with_the_hits(self):
        def queries(query):
            with CaptureQueriesContext(connection) as captured:
                search.render.entries(search.search(query).hits)
            return len(captured)
        for n in range(10):
            Category.objects.create(name=f"Dübel {n}", parent_category=self.fixing)
        self.assertEqual(queries("dübel 3"), queries("dübel"))
