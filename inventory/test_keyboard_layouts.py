from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .keyboard_layouts import LAYOUTS, layout_corrections, retype
from .location_lookup import resolve_location_reference
from .models import Location, LocationType

PREFIX = "https://inv.zam.haus/"


class RetypeTests(SimpleTestCase):
    def test_every_layout_has_the_same_keys(self):
        shapes = {name: [len(row) for row in rows] for name, rows in LAYOUTS.items()}
        self.assertEqual(len(set(map(tuple, shapes.values()))), 1, shapes)
        for name, rows in LAYOUTS.items():
            for key in (key for row in rows for key in row):
                self.assertEqual(len(key), 2, (name, key))

    def test_known_mismatches(self):
        url = "https://inv.zam.haus/loc/5/N1.B3"
        # Worked out by hand from the physical key positions.
        self.assertEqual(retype(url, "us", "de"), "httpsÖ--inv.yam.haus-loc-5-N1.B3")
        self.assertEqual(retype(url, "de", "us"), "https>&&inv.yam.haus&loc&5&N1.B3")
        self.assertEqual(retype("Zoom-Y_z", "us", "de"), "YoomßZ?y")

    def test_every_layout_pair_can_be_corrected(self):
        url = "https://inv.zam.haus/loc/42/R1.Shelf-B_3"
        for scanner in LAYOUTS:
            for host in LAYOUTS:
                with self.subTest(scanner=scanner, host=host):
                    scanned = retype(url, scanner, host)
                    corrections = list(layout_corrections(scanned, PREFIX))
                    if scanned == url or scanned.startswith(PREFIX):
                        # Nothing garbled in the prefix, nothing to derive.
                        self.assertEqual(corrections, [])
                    else:
                        self.assertIn(url, corrections)

    def test_values_without_a_garbled_prefix_are_left_alone(self):
        for value in ("N1.B3", "42", "/loc/5", "https://inv.zam.haus/loc/5", "httpsÖ--example.org-loc-5"):
            with self.subTest(value=value):
                self.assertEqual(list(layout_corrections(value, PREFIX)), [])


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
    DEFAULT_DOMAIN="https://inv.zam.haus",
)
class ScannedLayoutMismatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        box = LocationType.objects.create(name="Box", moveable=True)
        cls.source = Location.objects.create(type=room, name="Source", short_name="SRC")
        cls.parent = Location.objects.create(type=room, name="Destination", short_name="DST")
        cls.boxes = [
            Location.objects.create(type=box, name=f"Box {index}", short_name=f"Z{index}", parent_location=cls.source)
            for index in range(4)
        ]
        cls.user = get_user_model().objects.create_user(username="mover")
        cls.user.user_permissions.add(Permission.objects.get(codename="change_location", content_type__app_label="inventory"))

    def label_url(self, location):
        return settings.DEFAULT_DOMAIN + reverse("view_location", args=[location.pk, location.unique_identifier])

    def test_garbled_label_urls_resolve_to_their_location(self):
        box = self.boxes[0]
        for scanner, host in (("us", "de"), ("de", "us"), ("fr", "us"), ("us", "fr"), ("ch", "uk")):
            with self.subTest(scanner=scanner, host=host):
                self.assertEqual(resolve_location_reference(retype(self.label_url(box), scanner, host)), box)

    def test_unknown_locations_are_still_reported(self):
        garbled = retype(f"{settings.DEFAULT_DOMAIN}/loc/999999/NOPE", "us", "de")
        with self.assertRaisesMessage(ValidationError, "Location not found."):
            resolve_location_reference(garbled)

    def test_readings_of_different_locations_are_ambiguous(self):
        readings = [self.label_url(self.boxes[0]), self.label_url(self.boxes[1])]
        with patch("inventory.location_lookup.layout_corrections", return_value=iter(readings)):
            with self.assertRaisesMessage(ValidationError, "Ambiguous scan"):
                resolve_location_reference("httpsÖ--whatever")

    @override_settings(DEFAULT_DOMAIN="https://example.org")
    def test_prefix_follows_the_default_domain(self):
        box = self.boxes[0]
        self.assertEqual(resolve_location_reference(retype(self.label_url(box), "us", "de")), box)

    def test_move_here_accepts_scans_from_mismatched_layouts(self):
        self.client.force_login(self.user)
        lines = [
            retype(self.label_url(self.boxes[0]), "us", "de"),
            retype(self.label_url(self.boxes[1]), "de", "us"),
            # A French scanner on a US host types ";" for "m" in the domain.
            retype(self.label_url(self.boxes[2]), "fr", "us"),
        ]
        self.assertIn(";", lines[2])
        # Scanners end each scan with Enter; ";" still separates typed entries.
        identifiers = "\n".join(lines) + f"\n{self.boxes[3].unique_identifier};{self.boxes[3].pk}"
        response = self.client.post(
            reverse("locations_move_here", args=[self.parent.pk]), {"identifiers": identifiers}, follow=True,
        )
        self.assertContains(response, "Locations moved: 4. Errors: 0.")
        for box in self.boxes:
            box.refresh_from_db()
            self.assertEqual(box.parent_location_id, self.parent.pk)
