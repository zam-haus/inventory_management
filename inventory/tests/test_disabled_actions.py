from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from label_printing.models import LabelMedium, Printer
from ..models import Item, ItemLocation, Location, LocationType, MeasurementUnit


class DisabledActionTagTests(SimpleTestCase):
    def render(self, source, user=None, **context):
        with translation.override("en"):
            return Template("{% load actions %}" + source).render(Context({"user": user, **context}))

    def test_disabled_button_explains_itself(self):
        user = get_user_model()(username="reader")
        html = self.render('{% disabled_action "Cart" name="Change stock" reason=reason %}', user, reason="Not now <ever>")
        self.assertInHTML('<button class="btn btn-secondary" type="button" disabled aria-hidden="true">Cart</button>', html)
        self.assertIn('class="disabled-action" tabindex="0" role="button" aria-disabled="true" aria-label="Change stock"', html)
        self.assertIn('title="Not now &lt;ever&gt;"', html)
        self.assertNotIn("<ever>", html)

    def test_guests_see_nothing_logged_in_users_the_reason(self):
        self.assertEqual(self.render('{% disabled_action "Edit" %}'), "")
        user = get_user_model()(username="reader")
        self.assertIn("Ask an inventory admin", self.render('{% disabled_action "Edit" %}', user))


class UnavailableActionsStayVisibleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        room = LocationType.objects.create(name="Room", unique=True, moveable=True, deletable_in_frontend=True)
        cls.shelf = Location.objects.create(type=room, name="Shelf", short_name="SH")
        cls.item = Item.objects.create(name="Resistor")
        ItemLocation.objects.create(item=cls.item, location=cls.shelf, amount=10)
        # A printer for location labels, so printing them is available to whoever may print.
        printer = Printer.objects.create(name="Zebra", slug="zebra", language="zpl", host="192.0.2.1")
        LabelMedium.objects.create(printer=printer, name="57 × 32", width_mm=57, height_mm=32)

    def assertDisabled(self, response, name):
        self.assertContains(response, f'aria-disabled="true" aria-label="{name}"')

    def test_users_without_permission_see_disabled_actions(self):
        self.client.force_login(get_user_model().objects.create_user(username="reader"))
        for url, names in (
            (self.shelf.get_absolute_url(), ["Bewegen", "Etiketten drucken", "Standort auflösen",
                                             "Bestand von Resistor an Shelf · SH entnehmen oder hinzufügen"]),
            (self.item.get_absolute_url(), ["Sache bearbeiten", "Foto hinzufügen", "Datei hinzufügen",
                                            "Etiketten drucken", "Entnehmen", "Hinzufügen"]),
            (reverse("index_items"), ["Neue Sache anlegen"]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                for name in names:
                    self.assertDisabled(response, name)
                self.assertContains(response, "Bitte die Inventar-Admins um die Berechtigung.")

    def test_guests_do_not_see_actions_they_cannot_use(self):
        for url in (self.shelf.get_absolute_url(), self.item.get_absolute_url(), reverse("index_items"), reverse("index_locations")):
            with self.subTest(url=url):
                response = self.client.get(url)
                # Only the navbar scanner waits for JavaScript (a technical reason everyone sees).
                self.assertNotContains(response, 'role="button" aria-disabled="true"')  # {% disabled_action %}
                self.assertContains(response, "disabled-action", count=1)
                self.assertNotContains(response, "location-items-changeable")
        response = self.client.get(self.item.get_absolute_url())
        self.assertNotContains(response, "Dateien")
        self.assertNotContains(response, reverse("update_item", args=[self.item.pk]) + '"')

    def test_permitted_users_get_working_actions(self):
        self.client.force_login(get_user_model().objects.create_superuser(username="admin"))
        response = self.client.get(self.shelf.get_absolute_url())
        self.assertNotContains(response, 'role="button" aria-disabled="true"')  # {% disabled_action %}
        self.assertContains(response, reverse("location_dissolve", args=[self.shelf.pk]))

    def test_scan_button_waits_for_javascript(self):
        # A technical reason: guests see it disabled with the explanation, too.
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'title="Das braucht JavaScript.">')
        self.assertContains(response, 'data-scan-link disabled')
