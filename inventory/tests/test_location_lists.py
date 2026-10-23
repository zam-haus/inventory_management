from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from ..models import Item, ItemLocation, Location, LocationType, MeasurementUnit


class LocationListCollapseTests(TestCase):
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
        self.assertContains(response, "Hier befinden sich …")
        self.assertContains(response, '<a href="#location-items"><span class="location-contents-count" data-items-count>3</span> Sachen</a>', html=True)
        self.assertContains(response, '<a href="#location-children"><span class="location-contents-count">11</span> Unterstandorte</a>', html=True)
        for anchor in ("location-items", "location-unique-items", "location-children"):
            self.assertContains(response, f'id="{anchor}"')

    def test_only_lists_with_more_than_ten_entries_collapse(self):
        response = self.client.get(self.room.get_absolute_url())
        self.assertContains(response, '<input type="checkbox" class="list-collapse-state visually-hidden" id="location-children-expanded">', html=True)
        self.assertContains(response, '<label class="list-collapse-toggle" for="location-children-expanded">')
        self.assertContains(response, "Alle 11 anzeigen")
        self.assertNotContains(response, 'id="location-items-expanded"')
        self.assertNotContains(response, 'id="location-unique-items-expanded"')
        # Keeps collapsed entries findable with the browser's find-in-page (hidden="until-found").
        self.assertContains(response, "inventory/list_collapse.js")


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
