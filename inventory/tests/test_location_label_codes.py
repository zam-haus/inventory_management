"""Location labels hold the location's code via the label host (HTTPS://I.ZAM.HAUS/WH-1.R303.A)."""
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from ..label_ids import core, qr, services
from ..label_ids.testing import SETTINGS, InventoryFixture, code, make_id
from ..location_lookup import location_from_reference, locations_by_code
from ..models import Location, LocationFormerCode, LocationType

BASE = "https://inv.zam.haus"


@override_settings(**SETTINGS)
class LocationCodeResolverTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        shelf_type = LocationType.objects.create(name="Shelf", unique=True)
        compartment = LocationType.objects.create(name="Compartment")
        cls.shelf = Location.objects.create(name="Regal 303", short_name="R303", type=shelf_type, parent_location=cls.location)
        cls.part = Location.objects.create(name="Fach a", short_name="a", type=compartment, parent_location=cls.shelf)

    def scan(self, path, host="i.zam.haus"):
        return self.client.get(path, headers={"host": host})

    def test_label_content_is_the_uppercase_code(self):
        self.assertEqual(self.part.unique_identifier, "R303.a")
        self.assertEqual(qr.location_content(self.part.unique_identifier), "HTTPS://I.ZAM.HAUS/R303.A")

    def test_scanned_code_leads_to_the_location_in_any_case(self):
        for raw in ("R303.A", "r303.a", "R303.a"):
            with self.subTest(raw=raw):
                response = self.scan(f"/{raw}")
                self.assertEqual((response.status_code, response["Location"]), (302, BASE + self.part.get_absolute_url()))
        response = self.scan("/id/R303.A", host="inv.zam.haus")
        self.assertEqual(response["Location"], self.part.get_absolute_url())

    def test_former_codes_still_lead_there(self):
        LocationFormerCode.objects.create(code="R0303.a", location=self.part)
        self.assertEqual(self.scan("/R0303.A")["Location"], BASE + self.part.get_absolute_url())

    def test_codes_never_differ_only_in_case(self):
        """So a code in capitals (as on labels) always leads to exactly one location."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Location.objects.create(name="Fach A", short_name="A", type=self.part.type, parent_location=self.shelf)
        self.assertEqual(locations_by_code("R303.A"), [self.part])

    def test_unknown_code(self):
        self.assertContains(self.scan("/R999.Q"), "Invalid ID", status_code=404)

    def test_location_codes_come_first_and_are_never_issued_as_label_ids(self):
        # Short names may look like label IDs (none collide today); the location wins.
        lid = services.claim(make_id("K7R4X").code, self.item, None)
        odd = Location.objects.create(name="Odd", short_name=lid.code.lower(), type=self.shelf.type)
        self.assertEqual(self.scan(f"/{lid.code}")["Location"], BASE + odd.get_absolute_url())
        self.assertTrue(services.is_location_code(lid.code))
        LocationFormerCode.objects.create(code="5S8B24", location=odd)
        self.assertTrue(services.is_location_code("5s8b24"))
        with mock.patch.object(core, "generate", side_effect=["5S8B24", code("12345")]):
            created, = services.generate_batch(1)
        self.assertEqual(created.code, code("12345"))

    def test_scanning_a_location_label_while_moving(self):
        self.assertEqual(location_from_reference("HTTPS://I.ZAM.HAUS/R303.A"), self.part)
        self.assertEqual(location_from_reference("https://i.zam.haus/r303"), self.shelf)
        self.assertIsNone(location_from_reference("HTTPS://I.ZAM.HAUS/R999"))
