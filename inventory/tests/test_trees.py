from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .. import trees
from ..label_ids.testing import SETTINGS
from ..models import Category, Item, ItemLocation, Location, LocationType, MeasurementUnit, UniqueItem


@override_settings(**SETTINGS)
class TreeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        room = LocationType.objects.create(name="Room", unique=True, moveable=True, category=LocationType.Category.SPACE)
        shelf = LocationType.objects.create(name="Shelf", moveable=True, category=LocationType.Category.STORAGE_UNIT)
        box = LocationType.objects.create(name="Box", moveable=True, category=LocationType.Category.CONTAINER)
        cls.workshop = Location.objects.create(type=room, name="Workshop", short_name="WS")
        cls.office = Location.objects.create(type=room, name="Office", short_name="OF")
        cls.rack = Location.objects.create(type=shelf, name="Rack", short_name="R1", parent_location=cls.workshop)
        cls.crate = Location.objects.create(type=box, name="Crate", short_name="K1", parent_location=cls.rack)
        cls.gone = Location.objects.create(type=shelf, name="Gone", short_name="G1", parent_location=cls.office)
        cls.gone.delete()
        reserved = LocationType.objects.create(name="Numbered box", unique=True, category=LocationType.Category.CONTAINER)
        Location.objects.create(type=reserved, name="Reserved", short_name="K9", is_reserved=True)

        tools = Category.objects.create(name="Tools")
        hand = Category.objects.create(name="Hand tools", parent_category=tools)
        Category.objects.create(name="Empty")
        cls.pliers = Item.objects.create(name="Pliers", category=hand, measurement_unit=unit)
        cls.drill = Item.objects.create(name="drill", category=tools, kind=Item.Kind.UNIQUE, measurement_unit=unit)
        cls.loose = Item.objects.create(name="Loose thing", measurement_unit=unit)
        old = Item.objects.create(name="Old", category=hand, measurement_unit=unit)
        ItemLocation.objects.create(item=cls.pliers, location=cls.rack, amount=3)
        ItemLocation.objects.create(item=old, location=cls.rack, amount=1)
        old.delete()
        UniqueItem.objects.create(item=cls.drill, location=cls.crate)
        UniqueItem.objects.create(item=cls.drill, location=cls.crate, disposed_at=timezone.now())

    def test_locations_nested_with_counts(self):
        roots = trees.location_nodes()
        self.assertEqual([node.obj for node in roots], [self.office, self.workshop])  # by code: OF, WS
        office, workshop = roots
        self.assertEqual(office.children, [])  # the deleted shelf is gone; the reserved box is no root
        rack = workshop.children[0]
        self.assertEqual((rack.obj, rack.bulk, rack.unique, dict(rack.descendants)),
                         (self.rack, 1, 0, {"eurobox-open": 1}))  # one active item
        crate = rack.children[0]
        self.assertEqual((crate.obj, crate.bulk, crate.unique), (self.crate, 0, 1))  # one unique item still in use
        self.assertEqual(dict(workshop.descendants), {"bookshelf": 1, "eurobox-open": 1})  # by kind

    def test_location_page(self):
        content = self.client.get(reverse("index_locations")).content.decode()
        self.assertIn(f'<li id="loc-{self.workshop.pk}"><details open>', content)  # the top level is open
        # Only storage units below the workshop, only containers below the rack: no groups, each closed.
        self.assertNotIn('class="tree-group"', content)
        self.assertIn(f'<li id="loc-{self.rack.pk}"><details>', content)
        self.assertIn(f'<li id="loc-{self.crate.pk}" class="tree-leaf">', content)
        self.assertLess(content.index(f'id="loc-{self.rack.pk}"'), content.index(f'id="loc-{self.crate.pk}"'))
        self.assertIn('<use href="#tree-icon-bookshelf"/>', content)
        self.assertIn('<use href="#tree-icon-eurobox-open"/>', content)
        self.assertIn('<symbol id="tree-icon-geo-alt"', content)
        self.assertIn('title="1 storage unit"', content)
        self.assertIn('title="1 container"', content)
        self.assertIn('title="1 item"', content)
        self.assertIn('title="1 unique item"', content)
        # Counts: locations (building parts, storage units, containers) first, then items, then unique items.
        rack_row = content[content.index(f'id="loc-{self.rack.pk}"'):content.index(f'id="loc-{self.crate.pk}"')]
        self.assertLess(rack_row.index('title="1 container"'), rack_row.index('title="1 item"'))
        self.assertNotIn("Gone", content)
        self.assertNotIn("Reserved", content)
        self.assertIn(f'href="{self.rack.get_absolute_url()}"', content)
        self.assertIn(reverse("structure_overview"), content)

    def test_groups_only_where_they_set_kinds_apart(self):
        corner = Location.objects.create(type=self.workshop.type, name="Corner", short_name="CO", parent_location=self.workshop)
        box = self.crate.type
        loose = Location.objects.create(type=box, name="Loose box", short_name="K2", parent_location=self.workshop)
        compartment = Location.objects.create(type=self.rack.type, name="Compartment", short_name="a",
                                              parent_location=self.rack)
        content = self.client.get(reverse("index_locations")).content.decode()
        # The workshop has a building part, a storage unit and a container: storage units and containers grouped.
        self.assertIn(f'<li id="loc-{self.workshop.pk}-storage_unit" class="tree-group"><details open>', content)
        self.assertIn(f'<li id="loc-{self.workshop.pk}-container" class="tree-group"><details>', content)
        group = content[content.index(f'id="loc-{self.workshop.pk}-container"'):]
        self.assertIn(f'id="loc-{loose.pk}"', group)
        self.assertLess(content.index(f'id="loc-{corner.pk}"'), content.index(f'id="loc-{self.workshop.pk}-storage_unit"'))
        # The rack's compartment is a storage unit, too, but not grouped; its container is, being set apart.
        self.assertNotIn(f'id="loc-{self.rack.pk}-storage_unit"', content)
        self.assertIn(f'<li id="loc-{self.rack.pk}-container" class="tree-group"><details>', content)
        self.assertLess(content.index(f'id="loc-{compartment.pk}"'), content.index(f'id="loc-{self.rack.pk}-container"'))

    def test_levels_by_number(self):
        level = LocationType.objects.create(name="Level", unique=True, category=LocationType.Category.SPACE)
        for code in ("WH+1", "WH+0", "WH-1", "HH+0", "HH-2", "HH-1"):
            Location.objects.create(type=level, name=f"Level {code}", short_name=code)
        codes = [node.obj.short_name for node in trees.location_nodes()]
        self.assertEqual([code for code in codes if code[:2] in ("HH", "WH")],
                         ["HH-2", "HH-1", "HH+0", "WH-1", "WH+0", "WH+1"])

    def test_items_by_category(self):
        roots, uncategorized = trees.item_nodes()
        names = [node.obj.name for node in roots]  # with those the migrations create
        self.assertLess(names.index("Empty"), names.index("Tools"))
        tools = roots[names.index("Tools")]
        self.assertEqual((tools.bulk, tools.unique, [node.obj.name for node in tools.children], tools.leaves),
                         (1, 1, ["Hand tools"], [self.drill]))
        self.assertEqual(tools.children[0].leaves, [self.pliers])  # the deleted item is gone
        self.assertEqual(uncategorized, [self.loose])

    def test_item_page(self):
        content = self.client.get(reverse("index_items")).content.decode()
        tools = Category.objects.get(name="Tools")
        self.assertIn(f'<li id="cat-{tools.pk}"><details>', content)
        self.assertIn(f'<a class="tree-name" href="{tools.get_absolute_url()}">Tools</a>', content)
        self.assertLess(content.index("Hand tools"), content.index(">drill<"))  # subcategories first
        self.assertIn('<li id="cat-none"><details>', content)
        self.assertGreater(content.index('id="cat-none"'), content.index(">Pliers<"))  # at the end
        self.assertIn('<use href="#tree-icon-box-star"/>', content)
        self.assertIn(f'href="{self.pliers.get_absolute_url()}"', content)
        self.assertNotIn(">Old<", content)

    def test_unique_items_in_the_item_tree(self):
        first = UniqueItem.objects.get(item=self.drill, disposed_at__isnull=True)
        red = UniqueItem.objects.create(item=self.drill, name="red", location=self.crate)
        roots, _uncategorized = trees.item_nodes()
        tools = next(node for node in roots if node.obj.name == "Tools")
        self.assertEqual(tools.leaves[0].units, [first, red])  # still in the inventory, by name
        self.assertEqual((tools.bulk, tools.unique), (1, 2))  # unique items, not the items tracked as them
        content = self.client.get(reverse("index_items")).content.decode()
        drill = content[content.index(f'href="{self.drill.get_absolute_url()}"'):]
        drill = drill[:drill.index("</details>")]
        # Each named as everywhere: the item, its own name if any, its label ID (here none: its number).
        self.assertIn(f'<a href="{first.get_absolute_url()}">drill #{first.pk}</a>', drill)
        self.assertIn(f'<a href="{red.get_absolute_url()}">drill red #{red.pk}</a>', drill)
        self.assertEqual(drill.count("/item/unique/"), 2)
        # The list on the item's page names them the same way.
        self.assertContains(self.client.get(self.drill.get_absolute_url()),
                            f'<a href="{red.get_absolute_url()}">drill red #{red.pk}</a>')

    def test_old_searches_go_to_the_search(self):
        for name in ("index_items", "index_locations"):
            with self.subTest(name):
                self.assertRedirects(self.client.get(reverse(name), {"q": "pliers"}), f"{reverse('index')}?q=pliers",
                                     fetch_redirect_response=False)

    def test_names_are_escaped(self):
        Location.objects.create(type=self.workshop.type, name="<script>x</script>", short_name="XS")
        Item.objects.create(name="<script>y</script>", measurement_unit_id=1)
        for name in ("index_items", "index_locations"):
            with self.subTest(name):
                content = self.client.get(reverse(name)).content.decode()
                self.assertNotIn("<script>x", content)
                self.assertNotIn("<script>y", content)

    def test_queries_do_not_grow_with_the_tree(self):
        def count(name):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
            return len(queries)
        before = {name: count(name) for name in ("index_items", "index_locations")}
        for n in range(10):
            Location.objects.create(type=self.rack.type, name=f"Rack {n}", short_name=f"R{n + 10}",
                                    parent_location=self.workshop)
            Item.objects.create(name=f"Thing {n}", category=Category.objects.get(name="Tools"), measurement_unit_id=1)
        self.assertEqual({name: count(name) for name in before}, before)

    def test_category_page(self):
        tools = Category.objects.get(name="Tools")
        hand = Category.objects.get(name="Hand tools")
        response = self.client.get(tools.get_absolute_url())
        groups = response.context["groups"]
        # The items right in it first, then those of its subcategories, each group by name.
        self.assertEqual([(category, path, [entry.obj for entry in entries]) for category, path, entries in groups],
                         [(tools, "", [self.drill]), (hand, "Hand tools", [self.pliers])])
        content = response.content.decode()
        self.assertIn(f'href="{reverse("index_items")}#cat-{tools.pk}"', content)  # back to the tree
        self.assertIn(f'href="{hand.get_absolute_url()}"', content)
        self.assertNotIn(">Old<", content)
        self.assertEqual([entry.obj for entry in self.client.get(hand.get_absolute_url()).context["groups"][0][2]],
                         [self.pliers])

    def test_category_pages_of_fifty(self):
        tools = Category.objects.get(name="Tools")
        Item.objects.bulk_create([Item(name=f"Saw {n:02}", category=tools, measurement_unit_id=1) for n in range(55)])
        first = self.client.get(tools.get_absolute_url())
        self.assertEqual(sum(len(entries) for *_rest, entries in first.context["groups"]), 50)
        self.assertContains(first, "?page=2")
        second = self.client.get(tools.get_absolute_url(), {"page": 2})
        names = [entry.obj.name for *_rest, entries in second.context["groups"] for entry in entries]
        self.assertEqual(names, ["Saw 49", "Saw 50", "Saw 51", "Saw 52", "Saw 53", "Saw 54", "Pliers"])

    def test_item_pages_show_the_category_path(self):
        tools = Category.objects.get(name="Tools")
        hand = Category.objects.get(name="Hand tools")
        self.assertEqual(hand.ancestors, [tools])
        items = reverse("index_items")

        def path(url):
            content = self.client.get(url).content.decode()
            nav = content[content.index('class="item-breadcrumb"'):]
            return nav[:nav.index("</nav>")]
        pliers = path(self.pliers.get_absolute_url())
        self.assertIn(f'<a href="{items}#cat-{hand.pk}">Items</a>', pliers)  # the tree, opened at the category
        self.assertLess(pliers.index(f'<a href="{tools.get_absolute_url()}">Tools</a>'),
                        pliers.index(f'<a href="{hand.get_absolute_url()}">Hand tools</a>'))
        unique = UniqueItem.objects.filter(item=self.drill).first()
        self.assertIn(f'<a href="{tools.get_absolute_url()}">Tools</a>', path(unique.get_absolute_url()))
        loose = path(self.loose.get_absolute_url())
        self.assertIn(f'<a href="{items}#cat-none">Items</a>', loose)
        self.assertEqual(loose.count("<a "), 1)


@override_settings(**SETTINGS)
class LocationInfoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        shelf = LocationType.objects.create(name="Shelf", moveable=True, category=LocationType.Category.STORAGE_UNIT)
        cls.workshop = Location.objects.create(type=room, name="Workshop", short_name="WS")
        cls.rack = Location.objects.create(type=shelf, name="Rack", short_name="R1", parent_location=cls.workshop,
                                           purpose="Screws", physical_description="Left of the door")

    def test_a_location_in_brief(self):
        content = self.client.get(reverse("location_info", args=[self.rack.pk])).content.decode()
        self.assertNotIn('<nav class="navbar', content)  # only the window's content
        self.assertIn(f'<a href="{self.workshop.get_absolute_url()}">Workshop</a> <span class="loc-code">WS</span>', content)
        self.assertIn('<span aria-current="location">Screws</span>', content)
        self.assertIn("Left of the door", content)
        self.assertIn(f'href="{self.rack.get_absolute_url()}" data-location-open', content)
        self.rack.delete()
        self.assertEqual(self.client.get(reverse("location_info", args=[self.rack.pk])).status_code, 404)

    def test_code_chips_open_it_names_lead_to_the_page(self):
        for url in (reverse("index_locations"), self.workshop.get_absolute_url()):
            with self.subTest(url=url):
                content = self.client.get(url).content.decode()
                self.assertIn('id="location-info"', content)
                self.assertIn("inventory/location_info.js", content)
                self.assertIn(f'<span class="loc-code" data-location-info="{self.rack.pk}" role="button" tabindex="0"',
                              content)
        tree = self.client.get(reverse("index_locations")).content.decode()
        self.assertIn(f'<a href="{self.rack.get_absolute_url()}"><span class="loc-title">Screws</span></a>', tree)
