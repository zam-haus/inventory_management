from django.test import TestCase

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
