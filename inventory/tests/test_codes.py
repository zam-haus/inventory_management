"""Every way into the inventory reads codes alike (inventory/codes.py): the resolver, ?q= of the lists, location
fields and "Move here"."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .. import codes
from ..label_ids import services
from ..label_ids.testing import SETTINGS, InventoryFixture, make_id
from ..location_lookup import location_from_reference, resolve_location_reference
from ..models import Location, LocationFormerCode, LocationType
from ..numbered_location_views import create_numbered_container

BASE = "https://inv.zam.haus"


@override_settings(**SETTINGS)
class ResolveCodeTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        shelf_type = LocationType.objects.create(name="Shelf", unique=True)
        compartment = LocationType.objects.create(name="Compartment")
        cls.box_type = LocationType.objects.create(
            name="Kiste", auto_name_prefix="Kiste", auto_short_name_prefix="K", auto_short_name_padding_length=4,
            no_sublocations=True, unique=True, moveable=True, category="container", auto_sequence="0123456789")
        cls.shelf = Location.objects.create(name="Regal 303", short_name="R303", type=shelf_type,
                                            parent_location=cls.location)
        cls.part = Location.objects.create(name="Fach a", short_name="a", type=compartment, parent_location=cls.shelf)
        LocationFormerCode.objects.create(code="R0303", location=cls.shelf)
        cls.reserved = create_numbered_container(cls.box_type, reserved=True)
        cls.item_id = services.claim(make_id("K7R4X").code, cls.item, None)
        cls.location_id = services.claim(make_id("5S8B2").code, cls.shelf, None)
        cls.member = get_user_model().objects.create_user(username="member")
        cls.member.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["change_location", "add_location"]))

    def setUp(self):
        self.client.force_login(self.member)

    def readings(self):
        """(input, the location it names, or None for the item's label ID)."""
        item_code = self.item_id.code
        return [
            ("R303.a", self.part), ("r303.A", self.part), ("HTTPS://I.ZAM.HAUS/R303.A", self.part),
            ("https://i.zam.haus/r303", self.shelf), ("R0303", self.shelf), ("r0303", self.shelf),
            (self.shelf.get_absolute_url(), self.shelf), (BASE + self.part.get_absolute_url(), self.part),
            (self.location_id.display, self.shelf), (self.location_id.display.lower().replace("-", ""), self.shelf),
            (f"HTTPS://I.ZAM.HAUS/{self.location_id.code}", self.shelf),
            (self.item_id.display, None), (item_code.replace("0", "O"), None),
            (f"HTTPS://I.ZAM.HAUS/{item_code}/R303.A", None), (f"{BASE}/id/{item_code}", None),
        ]

    def test_one_reading_for_everything(self):
        for raw, location in self.readings():
            with self.subTest(raw=raw):
                found = codes.resolve_code(raw)
                if location is None:
                    self.assertEqual((found.kind, found.lid), (codes.LABEL_ID, self.item_id))
                else:
                    self.assertEqual(found.location if found.kind == codes.LOCATION else codes.label_id_location(found),
                                     location)
        self.assertEqual(codes.resolve_code(f"{self.item_id.code}/R303.A").at, self.part)
        self.assertEqual(codes.resolve_code("K0001").kind, codes.RESERVED)
        self.assertEqual(codes.resolve_code("Regal").kind, codes.INVALID)

    def test_the_resolver_and_its_lookup(self):
        for raw, location in self.readings():
            if "/" in raw.removeprefix("https://").removeprefix("HTTPS://"):
                continue  # URLs are scanned, not typed into the resolver's path
            with self.subTest(raw=raw):
                for url in (reverse("label_id_resolve", args=[raw]), reverse("label_id_lookup") + f"?q={raw}"):
                    response = self.client.get(url, follow=True)
                    expected = location.get_absolute_url() if location else self.item.get_absolute_url()
                    self.assertEqual(response.redirect_chain[-1][0].split("?")[0], expected)
        self.assertRedirects(self.client.get(reverse("label_id_lookup"), {"q": "k0001"}),
                             reverse("container_activate", args=[self.reserved.pk]), fetch_redirect_response=False)

    def test_old_list_searches_lead_to_the_search(self):
        for url in (reverse("index_locations"), reverse("index_items")):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url, {"q": "R303"}), f"{reverse('index')}?q=R303",
                                     fetch_redirect_response=False)
        # The search leads every code to what it belongs to: location codes, labels and label IDs.
        search = reverse("index")
        for raw, location in self.readings():
            with self.subTest(raw=raw):
                response = self.client.get(search, {"q": raw}, follow=True)
                expected = location.get_absolute_url() if location else self.item.get_absolute_url()
                self.assertEqual(response.redirect_chain[-1][0].split("?")[0], expected)
        self.assertEqual(self.client.get(search, {"q": "Regal"}).status_code, 200)  # text stays a search

    def test_location_fields_and_move_here(self):
        lookup = reverse("location_lookup")
        for raw, location in self.readings():
            with self.subTest(raw=raw):
                response = self.client.get(lookup, {"q": raw})
                if location is None:
                    self.assertEqual(response.status_code, 404)
                    self.assertIn("does not belong to a location", response.json()["error"])
                else:
                    self.assertEqual(response.json()["id"], location.pk)
                    self.assertEqual(resolve_location_reference(raw), location)
        self.assertEqual(resolve_location_reference(str(self.part.pk)), self.part)  # a number: its primary key
        self.assertIsNone(location_from_reference(str(self.part.pk)))  # not in searches

    def test_codes_that_read_as_label_ids_are_refused(self):
        clash = Location(name="Odd", short_name=self.item_id.code.lower(), type=self.shelf.type)
        with self.assertRaisesMessage(ValidationError, f"reads as the label ID {self.item_id.display}"):
            clash.full_clean(exclude=["unique_identifier", "locatable_identifier", "descriptive_identifier"])
        with self.assertRaises(ValidationError):
            LocationFormerCode(code=self.item_id.display).full_clean()
        out = StringIO()
        call_command("label_id_check", "--collisions", stdout=out)
        self.assertIn("0 collisions", out.getvalue())
        Location.objects.create(name="Odd", short_name=self.item_id.code, type=self.shelf.type)  # bypassing checks
        call_command("label_id_check", "--collisions", stdout=out)
        self.assertIn(f"reads as the ID {self.item_id.display}", out.getvalue())

    def test_typos_get_suggestions(self):
        wrong = self.item_id.code[:-1] + ("0" if self.item_id.code[-1] != "0" else "1")
        self.assertEqual(codes.resolve_code(wrong).reason, "checksum")
        self.assertContains(self.client.get(reverse("label_id_resolve", args=[wrong])), self.item_id.display,
                            status_code=404)
