from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from label_printing.design import variables as design_variables
from label_printing.layouts import Canvas, get_layout
from label_printing.tests.helpers import create_printers, generated
from ..forms import LocationMoveForm
from ..label_ids.testing import SETTINGS
from ..location_lookup import NotActivated, resolve_location_reference
from ..models import ChangeLog, Location, LocationType
from ..numbered_location_views import create_numbered_container
from ..structure_overview import structure_overview


def photo():
    content = BytesIO()
    Image.new("RGB", (40, 30), "blue").save(content, format="PNG")
    return SimpleUploadedFile("box.png", content.getvalue(), content_type="image/png")


@override_settings(**SETTINGS)
class ReservedContainerTests(TestCase):
    """Containers reserved in the admin with preprinted labels stay hidden until activated on first use."""

    @classmethod
    def setUpTestData(cls):
        room_type = LocationType.objects.create(name="Raum", unique=True, structure="room", category="space",
                                                admin_only=True)
        cls.box_type = LocationType.objects.create(
            name="Kiste", auto_name_prefix="Kiste", auto_short_name_prefix="K", auto_short_name_padding_length=4,
            no_sublocations=True, unique=True, moveable=True, category="container", auto_sequence="0123456789")
        cls.hall = Location.objects.create(type=room_type, name="Halle", short_name="HAL")
        Location.objects.create(type=cls.box_type, name="Kiste 524", short_name="K0524", parent_location=cls.hall)
        User = get_user_model()
        cls.admin = User.objects.create_superuser(username="admin")
        cls.member = User.objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["add_location", "change_location"]))
        cls.viewer = User.objects.create_user(username="viewer")

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.box = create_numbered_container(self.box_type, reserved=True)

    def activate_url(self, location=None):
        return reverse("container_activate", args=[(location or self.box).pk])

    def activate(self, **data):
        return self.client.post(self.activate_url(), {"parent_location": self.hall.pk, "purpose": "", **data})

    def test_reserving_in_the_admin(self):
        self.client.force_login(self.admin)
        url = reverse("admin:inventory_location_reserve")
        self.assertContains(self.client.get(url), "Kiste · K0526")  # K0525 is reserved already
        with patch("inventory.admin.admin_printing.print_and_report") as printed:
            response = self.client.post(url, {"type": self.box_type.pk, "count": 3, "print": "on", "label": "",
                                              "copies": 2})
        reserved = list(Location.objects.filter(is_reserved=True).order_by("short_name"))
        self.assertEqual([location.short_name for location in reserved], ["K0525", "K0526", "K0527", "K0528"])
        self.assertTrue(all(location.parent_location is None for location in reserved))
        self.assertEqual((printed.call_args.args[1:], printed.call_args.kwargs),
                         (("location", reserved[1:]), {"outcome_key": "", "copies": 2}))
        self.assertIn("id__in=", response.url)
        # Their numbers are taken: the next box created on the pages gets the one after them.
        self.assertEqual(self.box_type.next_free_number()[2], "K0529")
        self.assertContains(self.client.get(reverse("admin:inventory_location_changelist")), "Reserve containers")

    def test_reserving_needs_the_admin_and_add_location(self):
        url = reverse("admin:inventory_location_reserve")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 302)  # not staff: to the admin login
        self.member.is_staff = True
        self.member.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(get_user_model().objects.create_user(username="staff", is_staff=True))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_long_runs_print_in_chunks(self):
        from label_printing import services
        create_printers()
        boxes = [create_numbered_container(self.box_type, reserved=True) for _index in range(44)]
        with patch("label_printing.tasks.process_job.delay"):
            jobs, skipped = services.print_batch("location", [self.box, *boxes])
        self.assertEqual(([job.pages for job in jobs], skipped), ([20, 20, 5], []))
        self.assertEqual(len({job.batch for job in jobs}), 1)

    def test_reserved_containers_are_hidden(self):
        self.assertNotIn(self.box, Location.active.all())
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse("index_locations")), "K0525")
        for name in ("location-autocomplete", "parent_location_autocomplete"):
            self.assertEqual(self.client.get(reverse(name), {"q": "Kiste 525"}).json()["results"], [])
        self.assertNotIn(self.box, LocationMoveForm().fields["parent_location"].queryset)
        self.assertNotIn("K0525", str(structure_overview()))
        self.assertNotIn(self.box, [location for _name, location in design_variables.sample_subjects("location", 50)])
        # Its page leads to the activation.
        self.assertRedirects(self.client.get(self.box.get_absolute_url()), self.activate_url(),
                             fetch_redirect_response=False)

    def test_only_numbered_containers_without_a_parent_are_reserved(self):
        self.box.parent_location = self.hall
        with self.assertRaises(ValidationError):
            self.box.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.box.save()
        with self.assertRaises(ValidationError):
            Location(type=self.hall.type, name="Lager", short_name="LAG", is_reserved=True).full_clean()

    def test_guests_are_asked_to_log_in_and_members_without_permission_cannot_activate(self):
        page = self.client.get(self.activate_url())
        self.assertContains(page, "to activate it.")
        self.assertNotContains(page, 'name="parent_location"')
        self.assertEqual(self.activate().status_code, 302)  # to the login
        self.client.force_login(self.viewer)
        page = self.client.get(self.activate_url()).content.decode()
        self.assertIn('class="disabled-action"', page)
        self.assertEqual(self.activate().status_code, 403)
        self.assertTrue(Location.objects.get(pk=self.box.pk).is_reserved)

    def test_activating(self):
        self.client.force_login(self.member)
        response = self.activate(purpose="Karpfenprojekt", physical_description="blaue Eurobox", overview_photo=photo())
        self.assertRedirects(response, self.box.get_absolute_url(), fetch_redirect_response=False)
        box = Location.active.get(pk=self.box.pk)
        self.assertEqual((box.parent_location, box.purpose, box.physical_description), (self.hall, "Karpfenprojekt",
                                                                                         "blaue Eurobox"))
        self.assertTrue(box.overview_photo)
        activated = ChangeLog.objects.get(action=ChangeLog.Action.ACTIVATED)
        self.assertEqual((activated.location, activated.other_location, activated.actor), (box, self.hall, self.member))
        self.assertIn("purpose", [change["field"] for change in activated.changes])
        # Activated once: the page is its page now.
        self.assertRedirects(self.client.get(self.activate_url()), box.get_absolute_url(), fetch_redirect_response=False)

    def test_only_the_place_is_required(self):
        self.client.force_login(self.member)
        response = self.client.post(self.activate_url(), {"parent_location": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIn("parent_location", response.context["form"].errors)
        self.activate(next="/loc/")
        self.assertFalse(Location.objects.get(pk=self.box.pk).is_reserved)

    def test_the_label_and_typed_codes_lead_to_the_activation(self):
        self.client.force_login(self.member)
        target = self.activate_url()
        for url in (reverse("label_id_resolve", args=["K0525"]), reverse("label_id_resolve", args=["k0525"]),
                    reverse("label_id_lookup") + "?q=K0525", reverse("index") + "?q=k0525"):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), target, fetch_redirect_response=False)

    def test_location_fields_offer_the_activation(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("location_lookup"), {"q": "K0525"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["activate_url"], self.activate_url())
        self.assertIn("K0525 is not activated yet", response.json()["error"])
        with self.assertRaises(NotActivated):
            resolve_location_reference("HTTPS://I.ZAM.HAUS/K0525")

    def test_their_labels_render_without_a_place_or_purpose(self):
        _zebra, labels, _brother, tape = create_printers()
        for medium, size in ((labels, "57x32"), (tape, "tape12")):
            with self.subTest(size=size):
                layout = get_layout(f"design:{generated('location', size).pk}")
                rendered = layout.render(self.box, Canvas.for_medium(medium), medium, preview=True)
                self.assertEqual(rendered.snapshot["code"], "K0525")
