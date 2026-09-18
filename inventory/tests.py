from decimal import Decimal
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils.translation import override

from .models import Item, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class LocationsMoveHereTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.room_type = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.box_type = LocationType.objects.create(name="Box", moveable=True)
        cls.source = Location.objects.create(type=cls.room_type, name="Source", short_name="SRC")
        cls.parent = Location.objects.create(type=cls.room_type, name="Destination", short_name="DST")
        cls.box = Location.objects.create(type=cls.box_type, name="Box", short_name="B", parent_location=cls.source)
        cls.child = Location.objects.create(type=cls.box_type, name="Child", short_name="C", parent_location=cls.box)
        cls.unique = Location.objects.create(type=cls.room_type, name="Unique", short_name="U", parent_location=cls.source)
        cls.user = get_user_model().objects.create_user(username="mover")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("locations_move_here", kwargs={"pk": self.parent.pk})

    def post(self, identifiers):
        return self.client.post(self.url, {"identifiers": identifiers}, follow=True)

    def test_action_and_get_do_not_move_locations(self):
        response = self.client.get(self.parent.get_absolute_url())
        self.assertContains(response, f'href="{self.url}"')
        self.assertContains(response, "📥")
        response = self.client.get(self.url, {"identifiers": self.box.unique_identifier})
        self.assertContains(response, self.box.unique_identifier)
        self.box.refresh_from_db()
        self.assertEqual(self.box.parent_location_id, self.source.pk)

    def test_identifiers_separators_deduplication_and_snapshot_resolution(self):
        values = f"{self.box.unique_identifier};{self.child.unique_identifier}\n{self.unique.locatable_identifier}\t{self.unique.unique_identifier} {self.box.pk}"
        response = self.post(values)
        self.assertRedirects(response, self.parent.get_absolute_url())
        self.assertContains(response, "Locations moved: 3. Errors: 0.")
        for location in (self.box, self.child, self.unique):
            location.refresh_from_db()
            self.assertEqual(location.parent_location_id, self.parent.pk)

    def test_urls_follow_routing_and_accept_outdated_identifiers(self):
        stale_url = reverse("view_location", args=[self.box.pk, "outdated"])
        numeric_url = reverse("view_location2", args=[self.unique.pk])
        response = self.post(f"https://inv.zam.haus{stale_url}?scan=1#label;{numeric_url}")
        self.assertContains(response, "Locations moved: 2. Errors: 0.")
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_location_id, self.box.pk)
        self.assertEqual(self.child.unique_identifier, "DST.B.C")

    def test_partial_success_messages_and_retry_round_trip(self):
        bad = '<img/src=x/onerror=alert(1)>'
        missing = "UNKNOWN"
        response = self.post(f"{self.box.unique_identifier};{missing};{bad};999999999999999999999999999999")
        self.assertContains(response, "Locations moved: 1. Errors: 3.")
        self.assertNotContains(response, bad)
        self.assertContains(response, "&lt;img/src=x/onerror=alert(1)&gt;")
        links = [unescape(link) for link in re.findall(r'href="([^"]+)"', response.content.decode())]
        retries = [link for link in links if link.startswith(self.url + "?")]
        self.assertEqual(len(retries), 4)
        values = parse_qs(urlsplit(retries[-1]).query)["identifiers"][0]
        self.assertEqual(values, f"{missing}\n{bad}\n999999999999999999999999999999")
        retry = self.client.get(retries[-1])
        self.assertEqual(retry.context["form"]["identifiers"].value(), values)
        # Messages survive the redirect but disappear after being displayed.
        self.assertNotContains(self.client.get(self.parent.get_absolute_url()), "Locations moved:")

    def test_self_and_ancestor_moves_are_rejected(self):
        self.url = reverse("locations_move_here", kwargs={"pk": self.child.pk})
        response = self.post(f"{self.child.pk};{self.box.pk};{self.source.pk}")
        self.assertContains(response, "Locations moved: 0. Errors: 3.")
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_location_id, self.box.pk)

    def test_immovable_and_conflicting_locations_do_not_block_valid_moves(self):
        fixed_type = LocationType.objects.create(name="Fixed", unique=True)
        fixed = Location.objects.create(type=fixed_type, name="Fixed", short_name="FIX")
        Location.objects.create(type=self.box_type, name="Existing", short_name="B", parent_location=self.parent)
        response = self.post(f"{fixed.pk};{self.box.pk};{self.unique.pk}")
        self.assertContains(response, "Locations moved: 1. Errors: 2.")
        self.box.refresh_from_db()
        fixed.refresh_from_db()
        self.assertEqual(self.box.parent_location_id, self.source.pk)
        self.assertIsNone(fixed.parent_location_id)

    def test_only_location_detail_urls_are_accepted(self):
        response = self.post(f"/item/{self.box.pk};/loc/move/{self.box.pk};https://[broken;/loc/9999999999999999999999999999")
        self.assertContains(response, "Locations moved: 0. Errors: 4.")

    def test_database_identifier_conflict_rolls_back_only_that_move(self):
        Location.objects.create(type=self.room_type, name="Conflict", short_name="DST.B")
        response = self.post(f"{self.box.pk};{self.unique.pk}")
        self.assertContains(response, "Locations moved: 1. Errors: 1.")
        self.box.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.box.parent_location_id, self.source.pk)
        self.assertEqual(self.child.unique_identifier, "SRC.B.C")

    def test_numeric_identifiers_take_priority_over_database_ids(self):
        numeric = Location.objects.create(
            type=self.room_type, name="Numeric label", short_name=str(self.box.pk),
        )
        response = self.post(str(self.box.pk))
        self.assertContains(response, "Locations moved: 1. Errors: 0.")
        numeric.refresh_from_db()
        self.box.refresh_from_db()
        self.assertEqual(numeric.parent_location_id, self.parent.pk)
        self.assertEqual(self.box.parent_location_id, self.source.pk)

    def test_ambiguous_identifier_requires_url(self):
        Location.objects.create(
            type=self.room_type, name="Ambiguous", short_name="SRC.U", parent_location=self.parent,
        )
        response = self.post("SRC.U")
        self.assertContains(response, "Locations moved: 0. Errors: 1.")
        self.assertContains(response, "Ambiguous identifier; use the location URL.")
        self.assertContains(self.post(self.unique.get_absolute_url()), "Locations moved: 1. Errors: 0.")

    def test_empty_input_does_not_redirect_or_move(self):
        response = self.post(" ; \n\t;")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter at least one location.")
        self.box.refresh_from_db()
        self.assertEqual(self.box.parent_location_id, self.source.pk)

    def test_parent_that_cannot_have_children_is_rejected(self):
        self.room_type.no_sublocations = True
        self.room_type.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"identifiers": str(self.box.pk)}).status_code, 403)

    def test_anonymous_remote_requests_cannot_move_but_local_requests_can(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {"identifiers": str(self.box.pk)}).status_code, 302)
        self.box.refresh_from_db()
        self.assertEqual(self.box.parent_location_id, self.source.pk)
        session = self.client.session
        session["is_zam_local"] = True
        session.save()
        self.assertContains(self.post(str(self.box.pk)), "Locations moved: 1. Errors: 0.")

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {"identifiers": str(self.box.pk)}).status_code, 403)


class PrintableInventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        unique_type = LocationType.objects.create(name="Room", unique=True)
        child_type = LocationType.objects.create(name="Shelf")
        cls.root = Location.objects.create(type=unique_type, name="Workshop", short_name="W")
        cls.child = Location.objects.create(
            type=child_type, name="Shelf", short_name="S", parent_location=cls.root
        )
        # A unique child has an identifier that does not contain its parent's.
        cls.grandchild = Location.objects.create(
            type=unique_type, name="Box", short_name="BOX", parent_location=cls.child
        )
        cls.other = Location.objects.create(type=unique_type, name="Office", short_name="O")
        cls.unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(
            name="Screw", description="Steel\n<script>alert(1)</script>",
            measurement_unit=cls.unit, sale_price=Decimal("1.25"),
        )
        cls.root_entry = ItemLocation.objects.create(item=cls.item, location=cls.root, amount=12)
        cls.child_entry = ItemLocation.objects.create(item=cls.item, location=cls.child, amount=-25)
        cls.deep_entry = ItemLocation.objects.create(item=cls.item, location=cls.grandchild, amount=-9999)
        cls.other_item = Item.objects.create(name="Office only", measurement_unit=cls.unit)
        cls.other_entry = ItemLocation.objects.create(item=cls.other_item, location=cls.other, amount=-1)
        ItemImage.objects.create(item=cls.item, image="items/screw.jpg", description="Screw photo")
        ItemImage.objects.create(item=cls.item, image="items/label.jpg", description="Price label")

    def setUp(self):
        self.factory = RequestFactory()

    def report(self, locations=None, user=None, local=False, language="en", data=None, include_children=False):
        if data is None:
            data = {} if locations is None else {"locations": [location.pk for location in locations]}
        if include_children:
            data["include_children"] = "1"
        request = self.factory.get(reverse("print_inventory"), data)
        request.user = user if user is not None else get_user_model()()
        request.session = {"is_zam_local": local}
        with override(language):
            return resolve(request.path).func(request)

    def test_selection_page_does_not_list_inventory_until_locations_are_selected(self):
        response = self.report()
        self.assertContains(response, 'name="locations"')
        self.assertContains(response, "Workshop")
        self.assertNotContains(response, "Screw photo")
        self.assertNotContains(response, 'id="print-inventory"')

    def test_report_includes_descendants_and_excludes_unrelated_items(self):
        response = self.report([self.root], include_children=True)
        self.assertContains(response, '<article class="item">', count=3)
        self.assertContains(response, "12 pc")
        self.assertContains(response, "~25 pc")
        self.assertContains(response, "many pc")
        self.assertContains(response, "BOX")
        self.assertNotContains(response, "Office only")

    def test_overlapping_and_repeated_roots_do_not_duplicate_entries(self):
        response = self.report([self.root, self.child, self.root], include_children=True)
        self.assertContains(response, '<article class="item">', count=3)

    def test_multiple_separate_roots_and_location_specific_amounts(self):
        response = self.report([self.child, self.other], include_children=True)
        self.assertContains(response, '<article class="item">', count=3)
        self.assertContains(response, "few pc")
        self.assertNotContains(response, "12 pc")

    def test_price_description_and_all_images(self):
        response = self.report([self.grandchild])
        self.assertContains(response, "1.25 € / pc")
        self.assertContains(response, "Steel<br>&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, 'src="/media/items/screw.jpg"')
        self.assertContains(response, 'src="/media/items/label.jpg"')
        self.assertContains(response, 'loading="eager"', count=2)

    def test_missing_optional_fields_and_zero_price_and_amount(self):
        self.other_item.name = None
        self.other_item.save()
        response = self.report([self.other])
        self.assertContains(response, "Unnamed item")
        self.assertNotContains(response, "Price per unit")
        self.other_item.sale_price = Decimal("0.00")
        self.other_item.save()
        self.other_entry.amount = 0
        self.other_entry.save()
        response = self.report([self.other])
        self.assertContains(response, "0.00 € / pc")
        self.assertContains(response, "0 pc")

    def test_invalid_selection_shows_errors_without_partial_report(self):
        for value in ("not-an-id", "999999999999999999999999999999", "-123"):
            with self.subTest(value=value):
                response = self.report(data={"locations": [str(self.root.pk), value]})
                self.assertContains(response, 'class="errorlist"')
                self.assertNotContains(response, '<article class="item">')

    def test_sale_value_calculation(self):
        for amount, price, expected in (
            ("12", "1.25", "15.00"),
            ("-25", "1.25", "31.25"),
            ("2.125", "0.30", "0.63750"),
            ("-2.125", "0.30", "0.63750"),
            ("0", "1.25", "0"),
            ("12", "0.00", "0"),
            ("-25", "0.00", "0"),
            ("-1", "1.25", None),
            ("-9999", "1.25", None),
            ("12", None, None),
            (None, "1.25", None),
        ):
            with self.subTest(amount=amount, price=price):
                item = Item(sale_price=Decimal(price) if price is not None else None)
                entry = ItemLocation(
                    item=item, amount=Decimal(amount) if amount is not None else None,
                )
                self.assertEqual(
                    entry.sale_value, Decimal(expected) if expected is not None else None,
                )

    def test_report_sale_values_are_local_and_estimates_are_labelled(self):
        response = self.report([self.root], include_children=True)
        self.assertContains(response, "<strong>Sale value:</strong> 15.00 €", html=True)
        self.assertContains(
            response, "<strong>Estimated sale value:</strong> ~31.25 €", html=True,
        )
        response = self.report([self.child], language="de")
        self.assertContains(response, "Geschätzter Verkaufswert")
        self.assertContains(response, "~31,25 €")

    def test_report_omits_sale_value_for_unknown_quantity_or_price(self):
        self.assertNotContains(self.report([self.grandchild]), "sale value")
        self.assertNotContains(self.report([self.grandchild]), "Sale value")
        self.other_item.sale_price = Decimal("1.25")
        self.other_item.save()
        self.assertNotContains(self.report([self.other]), "Sale value")
        self.item.sale_price = None
        self.item.save()
        response = self.report([self.root])
        self.assertNotContains(response, "Sale value")
        self.assertNotContains(response, "Estimated sale value")

    def test_report_displays_zero_sale_value_and_rounds_fractional_value(self):
        self.other_entry.amount = Decimal("2.125")
        self.other_entry.save()
        self.other_item.sale_price = Decimal("0.30")
        self.other_item.save()
        self.assertContains(
            self.report([self.other]), "<strong>Sale value:</strong> 0.64 €", html=True,
        )
        self.other_item.sale_price = Decimal("0.00")
        self.other_item.save()
        self.assertContains(
            self.report([self.other]), "<strong>Sale value:</strong> 0.00 €", html=True,
        )

    def test_empty_location(self):
        ItemLocation.objects.filter(location=self.other).delete()
        self.assertContains(self.report([self.other]), "No items in the selected locations")

    def test_access_matches_location_list(self):
        response = self.report([self.root], user=AnonymousUser())
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)
        self.assertContains(self.report([self.root], user=AnonymousUser(), local=True), "Screw photo")

    def test_german_quantity_labels(self):
        response = self.report([self.root, self.other], language="de", include_children=True)
        self.assertContains(response, "viele pc")
        self.assertContains(response, "wenige pc")
        self.assertContains(response, "~25 pc")

    def test_query_count_does_not_grow_with_items_or_tree_depth(self):
        # Selection, entries and images; recursion adds parent relationships.
        with self.assertNumQueries(3):
            self.report([self.root])
        with self.assertNumQueries(4):
            self.report([self.root], include_children=True)
        for index in range(5):
            item = Item.objects.create(name=f"Extra {index}", measurement_unit=self.unit)
            ItemLocation.objects.create(item=item, location=self.grandchild, amount=index)
        with self.assertNumQueries(3):
            self.report([self.root])
        with self.assertNumQueries(4):
            self.report([self.root], include_children=True)

    def test_preselected_report_shows_direct_items_without_location_selector(self):
        response = self.report([self.root])
        self.assertContains(response, '<article class="item">', count=1)
        self.assertContains(response, "12 pc")
        self.assertNotContains(response, "~25 pc")
        self.assertNotContains(response, "many pc")
        self.assertNotContains(response, "<select")
        self.assertContains(response, "Also include child locations")
        self.assertNotContains(response, "Includes all child locations.")

    def test_recursion_toggle_preserves_all_selected_locations_and_can_be_disabled(self):
        locations = [self.root, self.other]
        direct = self.report(locations)
        recursive = self.report(locations, include_children=True)
        for response in (direct, recursive):
            for location in locations:
                self.assertContains(
                    response, f'<input type="hidden" name="locations" value="{location.pk}">', html=True,
                )
            self.assertNotContains(response, "<select")
        self.assertContains(direct, '<article class="item">', count=2)
        self.assertContains(direct, 'name="include_children" value="1"')
        self.assertContains(recursive, '<article class="item">', count=4)
        self.assertContains(recursive, "Only selected locations")
        self.assertNotContains(recursive, 'name="include_children"')
        disabled = self.report(data={"locations": [self.root.pk, self.other.pk], "include_children": "0"})
        self.assertContains(disabled, '<article class="item">', count=2)

    def test_empty_direct_location_can_include_stock_from_children(self):
        self.root_entry.delete()
        direct = self.report([self.root])
        self.assertContains(direct, "No items in the selected locations.")
        self.assertContains(direct, "Also include child locations")
        recursive = self.report([self.root], include_children=True)
        self.assertContains(recursive, '<article class="item">', count=2)
