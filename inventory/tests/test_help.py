from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from ..help_views import HelpView, help_context
from ..label_ids import services
from ..label_ids.testing import SETTINGS, InventoryFixture, make_id
from ..models import Item, Location, LocationType, UniqueItem

Category, Sequence, Structure = LocationType.Category, LocationType.Sequence, LocationType.Structure


@override_settings(**SETTINGS)
class HelpPageTests(InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()
        cls.extinguisher = Item.objects.create(name="Fire extinguisher", kind=Item.Kind.UNIQUE,
                                               measurement_unit=cls.unit)
        cls.unique_item = UniqueItem.objects.create(item=cls.extinguisher, location=cls.location)
        cls.lid = services.claim(make_id("K7R4X").code, cls.unique_item, None)

    def test_public_in_english(self):
        response = self.client.get(reverse("help"))
        self.assertTemplateUsed(response, "inventory/help/help_en.html")
        self.assertContains(response, "<h1>Items, locations, unique items</h1>", html=True)

    @override_settings(LANGUAGE_CODE="de")
    def test_german(self):
        response = self.client.get(reverse("help"))
        self.assertTemplateUsed(response, "inventory/help/help_de.html")
        self.assertContains(response, "<h1>Sachen, Standorte, Einzelobjekte</h1>", html=True)
        self.assertContains(response, "Ein Standort lässt sich nur löschen, wenn er leer ist")

    def test_other_languages_fall_back_to_german(self):
        with translation.override("fr"):
            self.assertEqual(HelpView().get_template_names(),
                             ["inventory/help/help_fr.html", "inventory/help/help_de.html"])

    @override_settings(LABEL_ID_NAME="ACMEid")
    def test_uses_the_configured_label_id_name(self):
        for language in ("en", "de"):
            with self.subTest(language), override_settings(LANGUAGE_CODE=language):
                response = self.client.get(reverse("help"))
                self.assertContains(response, "ACMEid")
                self.assertNotContains(response, "ZAMid")

    def test_menu_links_to_help(self):
        self.assertContains(self.client.get(reverse("index")), f'href="{reverse("help")}"')

    def test_pages_link_to_their_section(self):
        help_url = reverse("help")
        pages = {
            self.extinguisher.get_absolute_url(): "zamid",
            self.unique_item.get_absolute_url(): "zamid",
            self.location.get_absolute_url(): "codes",
            reverse("label_id_lookup"): "zamid",
        }
        for url, anchor in pages.items():
            with self.subTest(url):
                self.assertContains(self.client.get(url), f'href="{help_url}#{anchor}"')
        self.assertContains(self.client.get(self.location.get_absolute_url()), f'href="{help_url}#typen"')

    def test_resolver_host_links_to_the_inventory(self):
        response = self.client.get("/", headers={"host": "id.zam.haus"})
        self.assertContains(response, f'href="https://inv.zam.haus{reverse("help")}#zamid"')

    def test_new_item_form_links_to_the_kinds(self):
        self.client.force_login(get_user_model().objects.create_user(username="admin", is_superuser=True))
        self.assertContains(self.client.get(reverse("create_item")), f'href="{reverse("help")}#sachen"', count=2)

    def test_unknown_section_is_an_error(self):
        with self.assertRaises(ValueError):
            Template('{% load navigation %}{% help_link "nowhere" %}').render(Context())


@override_settings(**SETTINGS)
class HelpContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def kind(name, **fields):
            return LocationType.objects.create(name=name, **fields)

        level = kind("Level", category=Category.SPACE, structure=Structure.LEVEL, unique=True, admin_only=True)
        room = kind("Room", category=Category.SPACE, structure=Structure.ROOM, unique=True, admin_only=True)
        compartment = kind("Compartment", category=Category.STORAGE_UNIT, deletable_in_frontend=True,
                           auto_sequence=Sequence.LOWERCASE)
        shelf = kind("Shelf", category=Category.STORAGE_UNIT, unique=True, moveable=True, deletable_in_frontend=True,
                     area_numbering=True, auto_short_name_prefix="R", auto_short_name_padding_length=3,
                     auto_sequence=Sequence.NUMERIC, sublocation_type=compartment)
        box = kind("Box", category=Category.CONTAINER, unique=True, moveable=True, no_sublocations=True,
                   auto_short_name_prefix="K", auto_short_name_padding_length=4, auto_sequence=Sequence.NUMERIC)
        kind("Pallet", category=Category.CONTAINER, unique=True, moveable=True)
        kind("Mobile", unique=True, admin_only=True)

        def place(short_name, location_type, parent=None, **fields):
            return Location.objects.create(name=short_name, short_name=short_name, type=location_type,
                                           parent_location=parent, **fields)

        level0 = place("L0", level)
        room1 = place("R1", room, level0)
        compartment_a = place("a", compartment, place("R101", shelf, room1))
        place("K0001", box, compartment_a)
        place("K0002", box, room1)
        # Neither deleted nor reserved locations count for "usually stands in".
        place("K0003", box, level0, is_deleted=True)
        place("K0004", box, is_reserved=True)

    def setUp(self):
        self.context = help_context()
        self.groups = {group["category"]: group for group in self.context["type_groups"]}
        self.cards = {card["type"].name: card for group in self.context["type_groups"] for card in group["cards"]}

    def test_groups_by_category_from_the_outside_in(self):
        self.assertEqual(list(self.groups), ["space", "storage_unit", "container", "none"])
        self.assertEqual([card["type"].name for card in self.groups["space"]["cards"]], ["Level", "Room"])
        self.assertEqual([card["type"].name for card in self.groups["storage_unit"]["cards"]],
                         ["Shelf", "Compartment"])

    def test_code_patterns_and_examples(self):
        self.assertEqual(self.cards["Shelf"]["pattern"], "R + 3 digits")
        self.assertEqual(self.cards["Compartment"]["pattern"], "Code above + dot + letter a–z")
        self.assertEqual(self.cards["Room"]["pattern"], "Own code")
        self.assertEqual(self.cards["Box"]["type"].example, "K0002")
        self.assertEqual(self.cards["Compartment"]["type"].example, "R101.a")
        self.assertIsNone(self.cards["Pallet"]["type"].example)

    def test_where_types_usually_stand(self):
        self.assertEqual(self.cards["Box"]["where"], "Usually stands in: Compartment, Room")
        self.assertEqual(self.cards["Room"]["where"], "Usually stands in: Level")
        self.assertEqual(self.cards["Level"]["where"], "Top level")
        self.assertEqual(self.cards["Mobile"]["where"], "Top level, on its own")

    def test_shared_facts_are_said_once_per_category(self):
        self.assertEqual(self.groups["space"]["common"], [
            ("no", "Stays where it is"), ("yes", "Holds further locations"), ("lock", "Changed in the admin only")])
        self.assertEqual(self.cards["Room"]["facts"], [])
        self.assertIn(("yes", "Divided into Compartment"), self.cards["Shelf"]["facts"])
        self.assertIn(("no", "Holds only items, no locations"), self.cards["Box"]["facts"])

    def test_rules_name_the_types(self):
        rules = [text for _icon, text in self.context["rules"]]
        self.assertIn("Box hold only items, no further locations.", rules)
        self.assertIn("Shelf stand in a space (level, room, area) or on Pallet, never in a compartment or another "
                      "shelf.", rules)
        self.assertIn("Compartment exist only as part of another location. Their code builds on its code.", rules)
        self.assertIn("Level, Room and Mobile are created and changed by the admin team only. What is in them can "
                      "be moved by anyone with permission.", rules)

    @override_settings(LANGUAGE_CODE="de")
    def test_rendered_in_german(self):
        response = self.client.get(reverse("help"))
        self.assertContains(response, "Steht meist in: Compartment, Room")
        self.assertContains(response, "Gilt für alle Gebäudeteile")
