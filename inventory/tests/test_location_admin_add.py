from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import Location, LocationLabelTemplate, LocationType


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ], LANGUAGE_CODE="en",
)
class LocationAdminAddTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.template = LocationLabelTemplate.objects.create(
            name="Small", description="label 50 x 25\nqr {{ qr }}")
        LocationLabelTemplate.objects.exclude(pk=cls.template.pk).update(is_active=False)
        cls.room = LocationType.objects.create(name="Room", unique=True)
        cls.user = get_user_model().objects.create_user(username="admin", is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_invalid_add_form_with_label_template_rerenders_instead_of_crashing(self):
        response = self.client.post(reverse("admin:inventory_location_add"), {
            "type": self.room.pk, "name": "", "short_name": "FW",
            "location_set-TOTAL_FORMS": "0", "location_set-INITIAL_FORMS": "0",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(Location.objects.exists())

    def test_saved_location_still_shows_label_preview(self):
        location = Location.objects.create(type=self.room, name="Farbwerkstatt", short_name="FW")

        response = self.client.get(reverse("admin:inventory_location_change", args=[location.pk]))

        self.assertContains(response, reverse("label_template_preview",
                                              args=[self.template.pk, "location", location.pk]))
