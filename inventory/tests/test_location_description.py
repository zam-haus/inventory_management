from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import ChangeLog, Location, LocationType


@override_settings(LANGUAGE_CODE="en")
class LocationDescriptionTests(TestCase):
    """The physical description is changed like the purpose, except for the building structure."""

    @classmethod
    def setUpTestData(cls):
        room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space",
                                                admin_only=True)
        shelf_type = LocationType.objects.create(name="Regal", unique=True, category="storage_unit")
        cls.room = Location.objects.create(type=room_type, name="Halle", short_name="HAL",
                                           physical_description="mit Rolltor")
        cls.shelf = Location.objects.create(type=shelf_type, name="Regal 301", short_name="R301",
                                            parent_location=cls.room, physical_description="Holz, 4 Böden")
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["change_location", "view_changelog"]))
        cls.viewer = get_user_model().objects.create_user(username="viewer")

    def url(self, location):
        return reverse("location_description_update", args=[location.pk])

    def test_a_shelf_description_is_changed_and_logged(self):
        self.client.force_login(self.member)
        page = self.client.get(self.shelf.get_absolute_url()).content.decode()
        self.assertIn('data-field-editor-open="location-description-editor"', page)
        self.assertIn(f'action="{self.url(self.shelf)}"', page)
        response = self.client.post(self.url(self.shelf), {"physical_description": "Holz, 5 Böden\nblau lackiert"})
        self.assertRedirects(response, self.shelf.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(Location.objects.get(pk=self.shelf.pk).physical_description, "Holz, 5 Böden\nblau lackiert")
        event = ChangeLog.objects.get(location=self.shelf, action=ChangeLog.Action.CHANGED)
        self.assertEqual((event.actor, event.changes[0]["before"]), (self.member, "Holz, 4 Böden"))
        page = self.client.get(self.shelf.get_absolute_url()).content.decode()
        self.assertIn("physical description:", page)
        self.assertIn("<ins>Holz, 5 Böden\nblau lackiert</ins>", page)

    def test_the_dialog_saves_as_json(self):
        self.client.force_login(self.member)
        response = self.client.post(self.url(self.shelf), {"physical_description": ""}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(Location.objects.get(pk=self.shelf.pk).physical_description, "")

    def test_the_building_structure_keeps_its_description(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.url(self.room), {"physical_description": "x"}).status_code, 403)
        self.assertEqual(Location.objects.get(pk=self.room.pk).physical_description, "mit Rolltor")
        page = self.client.get(self.room.get_absolute_url()).content.decode()
        self.assertNotIn('id="location-description-editor"', page)
        self.assertIn("can only be changed in the admin.", page)

    def test_no_description_and_no_way_to_add_one_shows_nothing(self):
        self.client.force_login(self.member)
        Location.objects.filter(pk=self.room.pk).update(physical_description="")
        self.assertNotIn("Edit physical description", self.client.get(self.room.get_absolute_url()).content.decode())
        self.client.force_login(self.viewer)
        Location.objects.filter(pk=self.shelf.pk).update(physical_description="")
        self.assertNotIn("Edit physical description", self.client.get(self.shelf.get_absolute_url()).content.decode())
        # Whoever may add one sees the button.
        self.client.force_login(self.member)
        self.assertIn('data-field-editor-open="location-description-editor"',
                      self.client.get(self.shelf.get_absolute_url()).content.decode())

    def test_permission_is_needed(self):
        self.assertNotIn("Edit physical description", self.client.get(self.shelf.get_absolute_url()).content.decode())
        self.client.force_login(self.viewer)
        page = self.client.get(self.shelf.get_absolute_url()).content.decode()
        self.assertNotIn("Edit physical description", page)  # what cannot be changed has no pencil
        self.assertNotIn('id="location-description-editor"', page)
        self.assertEqual(self.client.post(self.url(self.shelf), {"physical_description": "x"}).status_code, 403)
