"""Responsibility edited in dialogs on the pages: the teams of a location (by its category: the building structure and
storage furniture with change_location, containers with view_internal_details), the team and person of a unique item
(change_uniqueitem and view_internal_details)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Team

from ..models import ChangeLog, Item, Location, LocationType, MeasurementUnit, UniqueItem


def user(name, *codenames):
    account = get_user_model().objects.create_user(username=name, first_name=name.title())
    account.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return account


class ResponsibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        room = LocationType.objects.create(name="Room", category=LocationType.Category.SPACE, unique=True)
        shelf = LocationType.objects.create(name="Shelf", category=LocationType.Category.STORAGE_UNIT, unique=True)
        box = LocationType.objects.create(name="Box", category=LocationType.Category.CONTAINER, unique=True)
        cls.room = Location.objects.create(type=room, name="Workshop", short_name="WS")
        cls.shelf = Location.objects.create(type=shelf, name="Shelf 1", short_name="R1", parent_location=cls.room)
        cls.box = Location.objects.create(type=box, name="Box 1", short_name="K1", parent_location=cls.shelf)
        cls.wood = Team.objects.create(group=Group.objects.create(name="Wood"), code="H")
        cls.metal = Team.objects.create(group=Group.objects.create(name="Metal"), code="M")
        cls.room.responsible_teams.add(cls.wood)
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        drill = Item.objects.create(name="Drill", kind=Item.Kind.SERIALIZED, measurement_unit=unit)
        cls.unique = UniqueItem.objects.create(item=drill, location=cls.box)
        cls.changer = user("changer", "change_location")
        cls.active = user("active", "view_internal_details")
        cls.keeper = user("keeper", "change_uniqueitem", "view_internal_details")

    def save_teams(self, location, *teams):
        return self.client.post(reverse("location_responsibility_update", args=[location.pk]),
                                {"responsible_teams": [team.pk for team in teams]})

    def test_storage_furniture_and_building_with_change_location(self):
        self.client.force_login(self.changer)
        self.assertContains(self.client.get(self.shelf.get_absolute_url()), 'data-field-editor-open="location-responsibility-editor"')
        self.assertRedirects(self.save_teams(self.shelf, self.metal), self.shelf.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(list(self.shelf.responsible_teams.all()), [self.metal])
        self.assertEqual(self.save_teams(self.room).status_code, 302)  # none: the teams of the location above
        self.assertEqual(list(self.room.responsible_teams.all()), [])
        # Not containers.
        self.assertNotContains(self.client.get(self.box.get_absolute_url()), "location-responsibility-editor")
        self.assertEqual(self.save_teams(self.box, self.wood).status_code, 403)

    def test_containers_by_who_may_see_contact_details(self):
        self.client.force_login(self.active)
        page = self.client.get(self.box.get_absolute_url())
        self.assertContains(page, 'data-field-editor-open="location-responsibility-editor"')
        self.assertContains(page, "Ohne eigenes Team sind die von")  # the shelf's, from the room
        self.save_teams(self.box, self.metal)
        self.assertEqual(list(self.box.responsible_teams.all()), [self.metal])
        entry = ChangeLog.objects.filter(location=self.box).first()
        self.assertEqual((entry.actor, entry.changes[0]["field"], entry.changes[0]["after"]),
                         (self.active, "responsible_teams", "Metal"))
        # Not the shelf, nor the building structure.
        self.assertNotContains(self.client.get(self.shelf.get_absolute_url()), "location-responsibility-editor")
        self.assertEqual(self.save_teams(self.shelf, self.metal).status_code, 403)
        self.assertEqual(self.save_teams(self.room, self.metal).status_code, 403)

    def test_guests_see_no_pencil_and_cannot_save(self):
        self.assertNotContains(self.client.get(self.box.get_absolute_url()), "location-responsibility-editor")
        self.assertTrue(self.save_teams(self.box, self.metal).url.startswith(reverse("login")))
        self.assertEqual(list(self.box.responsible_teams.all()), [])

    def save_unique(self, **data):
        return self.client.post(reverse("unique_item_responsibility_update", args=[self.unique.pk]), data)

    def test_unique_items_by_who_may_change_them_and_see_contact_details(self):
        self.client.force_login(self.keeper)
        page = self.client.get(self.unique.get_absolute_url())
        self.assertContains(page, 'data-field-editor-open="unique-item-responsibility-editor"')
        self.assertContains(page, "Wie am Standort")
        self.assertRedirects(self.save_unique(responsible_team=self.metal.pk, responsible_user=self.active.pk),
                             self.unique.get_absolute_url(), fetch_redirect_response=False)
        self.unique.refresh_from_db()
        self.assertEqual((self.unique.responsible_team, self.unique.responsible_user), (self.metal, self.active))
        # Neither permission alone.
        for account in (self.active, user("helper", "change_uniqueitem")):
            with self.subTest(account=account.username):
                self.client.force_login(account)
                self.assertNotContains(self.client.get(self.unique.get_absolute_url()), "unique-item-responsibility-editor")
                self.assertEqual(self.save_unique(responsible_team="").status_code, 403)
        self.unique.refresh_from_db()
        self.assertEqual(self.unique.responsible_team, self.metal)
