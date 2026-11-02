from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from ..models import Category, Item, ItemLocation, Location, LocationType, MeasurementUnit, UniqueItem


class LocationListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        box = LocationType.objects.create(name="Box", moveable=True)
        cls.room = Location.objects.create(type=room, name="Store", short_name="ST")
        for index in range(11):
            Location.objects.create(type=box, name=f"Box {index}", short_name=f"B{index}", parent_location=cls.room)
        for index in range(3):
            ItemLocation.objects.create(item=Item.objects.create(name=f"Part {index}"), location=cls.room, amount=1)

    def test_overview_links_to_sections_with_counts(self):
        response = self.client.get(self.room.get_absolute_url())
        self.assertContains(response, "Hier sind …")
        icon = lambda name: Template(f'{{% load icons %}}{{% icon "{name}" %}}').render(Context())
        self.assertContains(response, f'<a href="#location-items">{icon("boxes")} <span class="location-contents-count" data-items-count>3</span> Mengenartikel</a>', html=True)
        self.assertContains(response, f'<a href="#location-children">{icon("geo-alt")} <span class="location-contents-count">11</span> Unterstandorte</a>', html=True)
        for anchor in ("location-items", "location-unique-items", "location-children"):
            self.assertContains(response, f'id="{anchor}"')
            # The same section, with the same icon, in the jump buttons for further down the page.
            self.assertContains(response, f'<a class="btn btn-light" href="#{anchor}"', count=1)
        # Back to the top: on every page with the base layout, once scrolled down at all.
        self.assertContains(response, 'title="Zum Seitenanfang springen"')
        self.assertContains(self.client.get(reverse("index_items")), '<nav class="page-jump" aria-label="Springen zu" data-page-jump hidden>')

    def test_long_lists_come_in_pages_while_scrolling(self):
        box = Location.objects.get(short_name="B0").type
        for index in range(11, 55):
            Location.objects.create(type=box, name=f"Box {index}", short_name=f"B{index}", parent_location=self.room)
        tools = Category.objects.create(name="Tools")
        for index in range(3, 55):
            ItemLocation.objects.create(item=Item.objects.create(name=f"Part {index:02}", category=tools),
                                        location=self.room, amount=1)
        response = self.client.get(self.room.get_absolute_url())
        self.assertEqual((len(response.context["item_entries"]), len(response.context["child_entries"])), (50, 50))
        items = reverse("location_rows", args=[self.room.pk, "items"])
        self.assertContains(response, f'data-result-next="{items}?offset=50"')
        self.assertContains(response, f'data-result-next="{reverse("location_rows", args=[self.room.pk, "children-all"])}?offset=50"')
        self.assertNotContains(response, "list-collapse")
        more = self.client.get(items, {"offset": 50, "partial": "1"})
        self.assertEqual([entry.obj.name for entry in more.context["entries"]],
                         ["Part 53", "Part 54", "Part 0", "Part 1", "Part 2"])
        # The category goes on from the page before: a heading only where it changes.
        self.assertEqual([entry.group for entry in more.context["entries"]][:3], [None, None, ("Ohne Kategorie", "")])
        self.assertTrue(more.content.decode().lstrip().startswith("<template data-result-entries>"))
        self.assertNotIn("data-result-next", more.content.decode())
        boxes = self.client.get(reverse("location_rows", args=[self.room.pk, "children-all"]), {"offset": 50})
        self.assertEqual(len(boxes.context["entries"]), 5)
        self.assertEqual(self.client.get(reverse("location_rows", args=[self.room.pk, "children-space"])).status_code, 404)


class SubLocationCategoryTests(TestCase):
    """Sub-locations are listed per category of their type, with shortcuts to adding and moving here."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        Category = LocationType.Category
        area = LocationType.objects.create(name="Bereich", unique=True, structure="area", category=Category.SPACE)
        cls.shelf_type = LocationType.objects.create(
            name="Regal", unique=True, area_numbering=True, category=Category.STORAGE_UNIT,
            auto_short_name_prefix="R", auto_sequence="0123456789")
        box = LocationType.objects.create(name="Kiste", unique=True, moveable=True, category=Category.CONTAINER)
        cls.area = Location.objects.create(type=area, name="Holzbaubühne", short_name="HBB")
        Location.objects.create(type=area, name="Holzbaubühne unten", short_name="HBB1", parent_location=cls.area)
        Location.objects.create(type=box, name="Kiste 1", short_name="K1", parent_location=cls.area)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(codename__in=["add_location", "change_location"]))

    def test_one_panel_per_category_with_shortcuts(self):
        self.client.force_login(self.member)
        page = self.client.get(self.area.get_absolute_url()).content.decode()
        anchors = ["location-children-space", "location-children-storage-unit", "location-children-container"]
        for anchor in anchors:
            self.assertIn(f'id="{anchor}"', page)
            self.assertIn(f'href="#{anchor}"', page)
        self.assertLess(page.index(f'id="{anchors[0]}"'), page.index(f'id="{anchors[1]}"'))
        self.assertLess(page.index(f'id="{anchors[1]}"'), page.index(f'id="{anchors[2]}"'))
        self.assertNotIn('id="location-children"', page)
        self.assertNotIn("{#", page)
        # The storage units' panel shows while empty, so its + is there to add the first one.
        storage_panel = page[page.index(f'id="{anchors[1]}"'):page.index(f'id="{anchors[2]}"')]
        self.assertIn(reverse("numbered_location_create", args=[self.area.pk]), storage_panel)
        container_panel = page[page.index(f'id="{anchors[2]}"'):]
        self.assertIn('data-modal-open="locations-move-here-modal"', container_panel)
        # "At this location" comes before both columns.
        self.assertLess(page.index('id="location-stored-heading"'), page.index('class="location-layout'))

    def test_add_actions_show_what_they_add(self):
        # Without their text (actions.js) the + buttons still differ: the icon of what they add, with a plus.
        LocationType.objects.filter(name="Kiste").update(auto_short_name_prefix="K",
                                                         auto_sequence=LocationType.Sequence.NUMERIC)
        self.client.force_login(self.member)
        page = self.client.get(self.area.get_absolute_url()).content.decode()
        actions = page[page.index("data-action-group"):page.index("location-summary")]
        for url, kind in ((reverse("numbered_location_create", args=[self.area.pk]), "bi-bookshelf"),
                          (reverse("container_create", args=[self.area.pk]), "bi-eurobox-open")):
            button = actions[actions.index(f'href="{url}"'):]
            button = button[:button.index("</a>")]
            self.assertIn('class="action-icon action-add-icon"', button)
            self.assertIn(kind, button)
            self.assertIn("action-add-plus", button)
        self.client.force_login(get_user_model().objects.create_user(username="reader"))  # disabled, same icons
        page = self.client.get(self.area.get_absolute_url()).content.decode()
        actions = page[page.index("data-action-group"):page.index("location-summary")]
        self.assertEqual(actions.count('class="action-icon action-add-icon"'), 2)
        # The panels' + buttons, too: what each adds (items, unique items, storage units, containers).
        panels = page[page.index("location-summary"):]
        for kind in ("bi-boxes", "bi-box-star", "bi-bookshelf", "bi-eurobox-open"):
            self.assertIn(f'class="bi {kind} action-add-kind"', panels)
        self.assertNotIn("bi-plus-lg", page)

    def test_guests_see_no_empty_storage_unit_panel(self):
        page = self.client.get(self.area.get_absolute_url()).content.decode()
        self.assertNotIn('id="location-children-storage-unit"', page)
        self.assertIn('id="location-children-container"', page)
        self.assertNotIn('data-modal-open="locations-move-here-modal"', page)

    def test_missing_category_follows_from_the_type(self):
        kind = LocationType(name="Teilbereich", structure="area", unique=True)
        kind.full_clean()
        self.assertEqual(kind.category, LocationType.Category.SPACE)
        kind = LocationType(name="Fach", category=LocationType.Category.CONTAINER, structure="area")
        with self.assertRaises(ValidationError):
            kind.full_clean()


class SubtreeTests(TestCase):
    """The lists of a location's page reach down to the depth chosen (?depth=) and are searched (?q=, live_search.js),
    views.LocationLists."""

    @classmethod
    def setUpTestData(cls):
        MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        shelf = LocationType.objects.create(name="Shelf", moveable=True, category=LocationType.Category.STORAGE_UNIT)
        cls.store = Location.objects.create(type=room, name="Store", short_name="ST")
        cls.shelf = Location.objects.create(type=shelf, name="Shelf", short_name="S1", parent_location=cls.store)
        cls.compartment = Location.objects.create(type=shelf, name="Compartment", short_name="a", parent_location=cls.shelf)
        # Its code starts as the store's, but it is not below it.
        cls.other = Location.objects.create(type=room, name="Store annex", short_name="ST1")
        cls.gone = Location.objects.create(type=shelf, name="Old shelf", short_name="S9", parent_location=cls.store,
                                           is_deleted=True)
        tools = Category.objects.create(name="Tools")
        cls.hammer = Item.objects.create(name="Hammer", category=tools)
        cls.drill = Item.objects.create(name="Drill", category=tools)
        cls.saw = Item.objects.create(name="Saw")
        ItemLocation.objects.create(item=cls.hammer, location=cls.store, amount=1)
        ItemLocation.objects.create(item=cls.drill, location=cls.shelf, amount=2)
        ItemLocation.objects.create(item=cls.saw, location=cls.compartment, amount=3)
        ItemLocation.objects.create(item=cls.hammer, location=cls.compartment, amount=4)
        ItemLocation.objects.create(item=Item.objects.create(name="Glue"), location=cls.other, amount=1)
        ItemLocation.objects.create(item=Item.objects.create(name="Lost drill"), location=cls.gone, amount=1)
        lathe = Item.objects.create(name="Lathe", kind=Item.Kind.SERIALIZED, measurement_unit_id=1)
        cls.lathe = UniqueItem.objects.create(item=lathe, name="big", location=cls.compartment)

    def page(self, location=None, **params):
        return self.client.get((location or self.store).get_absolute_url(), params)

    def rows(self, response):
        return [(entry.row.item.name, entry.row.location.short_name) for entry in response.context["item_entries"]]

    def test_in_tree(self):
        def below(depth, itself=True):
            return set(Location.objects.filter(self.store.in_tree("", depth, itself)).values_list("short_name", flat=True))
        self.assertEqual(below(0), {"ST"})
        self.assertEqual(below(1), {"ST", "S1", "S9"})
        self.assertEqual(below(2), {"ST", "S1", "S9", "a"})
        self.assertEqual(below(None), {"ST", "S1", "S9", "a"})
        self.assertEqual(below(1, itself=False), {"S1", "S9"})

    def test_only_here_at_first(self):
        response = self.page()
        self.assertEqual(self.rows(response), [("Hammer", "ST")])
        self.assertEqual(response.context["unique_entries"], [])
        self.assertContains(response, "Nur hier")
        self.assertIsNone(response.context["item_entries"][0].at)

    def test_levels_below(self):
        response = self.page(depth="1")
        # By category, then by name; the places below named in the row, the deleted shelf left out.
        self.assertEqual(self.rows(response), [("Drill", "S1"), ("Hammer", "ST")])
        self.assertEqual(response.context["item_entries"][0].at, self.shelf)
        self.assertEqual(response.context["items_count"], 2)
        response = self.page(depth="all")
        self.assertEqual(self.rows(response), [("Drill", "S1"), ("Hammer", "ST"), ("Hammer", "a"), ("Saw", "a")])
        self.assertEqual([entry.obj for entry in response.context["unique_entries"]], [self.lathe])
        self.assertContains(response, self.compartment.get_absolute_url())
        # The hammer's places in the list are not named again as its other places.
        self.assertEqual(response.context["item_entries"][1].places, [])
        # Anything else is only here.
        self.assertEqual(self.rows(self.page(depth="9")), [("Hammer", "ST")])

    def test_further_rows_keep_the_depth(self):
        tools = Category.objects.get(name="Tools")
        for index in range(55):
            ItemLocation.objects.create(item=Item.objects.create(name=f"Part {index:02}", category=tools),
                                        location=self.shelf, amount=1)
        response = self.page(depth="2")
        items = reverse("location_rows", args=[self.store.pk, "items"])
        self.assertContains(response, f'data-result-next="{items}?depth=2&amp;offset=50"')
        more = self.client.get(items, {"depth": "2", "offset": 50, "partial": "1"})
        self.assertEqual([entry.row.item.name for entry in more.context["entries"]],
                         [*(f"Part {index}" for index in range(47, 55)), "Saw"])
        self.assertEqual([entry.group for entry in more.context["entries"]][-1:], [("Ohne Kategorie", "")])

    def test_search_filters_every_list(self):
        response = self.page(q="hammer")
        self.assertEqual(self.rows(response), [("Hammer", "ST")])
        response = self.page(q="hammer", depth="all")
        self.assertEqual(self.rows(response), [("Hammer", "ST"), ("Hammer", "a")])
        self.assertEqual(response.context["unique_entries"], [])
        self.assertEqual(response.context["child_entries"], [])
        self.assertContains(response, "Nichts gefunden.", count=2)
        response = self.page(q="big lathe", depth="2")
        self.assertEqual([entry.obj for entry in response.context["unique_entries"]], [self.lathe])
        response = self.page(q="compartment", depth="all")
        self.assertEqual([entry.obj for entry in response.context["child_entries"]], [self.compartment])
        # Its category's keywords find items and unique items here, as no category is a hit.
        tools = Category.objects.get(name="Tools")
        tools.keywords = "Werkzeug, Tool"
        tools.save()
        self.assertEqual(self.rows(self.page(q="werkzeug", depth="1")), [("Drill", "S1"), ("Hammer", "ST")])
        # Not what is elsewhere, nor the location itself.
        self.assertEqual(self.rows(self.page(q="glue", depth="all")), [])
        self.assertEqual(self.page(q="store", depth="all").context["child_entries"], [])

    def test_partial_is_only_the_lists(self):
        response = self.page(q="saw", depth="all", partial="1")
        content = response.content.decode()
        self.assertTrue(content.lstrip().startswith('<div class="location-layout'))
        self.assertIn("data-location-contents-nav", content)
        self.assertIn("data-location-jump-links", content)
        self.assertIn('data-status="1 Mengenartikel gefunden', content)
        self.assertNotIn("<html", content)
        self.assertNotIn('id="location-quick-items"', content)
        self.assertNotIn("data-quick-items-slot", content)
        # Without words the quick-items keep their place on the page.
        self.assertIn("data-quick-items-slot", self.page(partial="1").content.decode())

    def test_search_field_and_depth(self):
        response = self.page(q="saw", depth="2")
        self.assertContains(response, 'aria-controls="location-lists"')
        self.assertContains(response, 'name="q" value="saw"')
        self.assertContains(response, '<option value="2" selected>')
        self.assertContains(response, 'href="#location-search"')
        self.assertContains(response, "live_search.js")
        # The magnifier's texts, for the hint after going to the field (navbar.js).
        self.assertContains(response, 'data-text-again="Noch einmal klicken oder {keys} drücken, um alles zu durchsuchen"')

    def test_queries_do_not_grow_with_the_rows(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries(**params):
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.page(**params).status_code, 200)
            return len(captured)
        lathe = self.lathe.item
        ItemLocation.objects.create(item=Item.objects.create(name="Part"), location=self.compartment, amount=1)
        UniqueItem.objects.create(item=lathe, name="part", location=self.shelf)
        before = [queries(depth="all"), queries(depth="all", q="part")]
        for index in range(5):
            ItemLocation.objects.create(item=Item.objects.create(name=f"Part {index}"), location=self.compartment, amount=1)
            UniqueItem.objects.create(item=lathe, name=f"part {index}", location=self.shelf)
        self.assertEqual([queries(depth="all"), queries(depth="all", q="part")], before)
