import shutil
import tempfile
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import Team
from ..actor import acting_as
from ..models import Item, ItemLocation, LabelId, Location, LocationType, UniqueItem, UniqueItemEvent, UsageLevel
from ..label_ids import services
from ..label_ids.views import label_preview_url
from ..label_ids.testing import SETTINGS, InventoryFixture, make_id, local_group


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))


class UniqueItemFixture(InventoryFixture):
    @classmethod
    def create_unique_items(cls):
        cls.create_inventory()
        User = get_user_model()
        # Invented people only.
        cls.member = User.objects.create_user(username="member", first_name="Alex", last_name="Example",
                                              email="alex@example.org")
        cls.member.groups.add(local_group())
        cls.insider = User.objects.create_user(username="insider", first_name="Sam", last_name="Sample")
        cls.insider.groups.add(local_group())
        grant(cls.insider, "view_internal_details", "dispose_uniqueitem")
        cls.owner = User.objects.create_user(username="owner", first_name="Robin", last_name="Private",
                                             email="robin@example.org")
        cls.team = Team.objects.create(group=Group.objects.create(name="Woodworking"))
        cls.shelf = Location.objects.create(name="Shelf", short_name="S", type=cls.kind, parent_location=cls.location)
        cls.extinguisher = Item.objects.create(name="Fire extinguisher", kind=Item.Kind.UNIQUE,
                                               usage_level=UsageLevel.GREEN, measurement_unit=cls.unit)
        cls.unique_item = UniqueItem.objects.create(item=cls.extinguisher, location=cls.location)
        cls.lid = services.claim(make_id("K7R4X").code, cls.unique_item, None)


@override_settings(**SETTINGS)
class UniqueItemModelTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def test_unique_item_types_cannot_be_sold(self):
        item = Item(name="Saw", kind=Item.Kind.UNIQUE, for_sale=True, sale_price=Decimal("5"), measurement_unit=self.unit)
        with self.assertRaises(ValidationError) as raised:
            item.full_clean()
        self.assertEqual(set(raised.exception.message_dict), {"for_sale", "sale_price"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE, sale_price=Decimal("5"), measurement_unit=self.unit)

    def test_a_price_means_for_sale(self):
        item = Item.objects.create(name="Screws", sale_price=Decimal("0.10"), measurement_unit=self.unit)
        self.assertIs(item.for_sale, True)
        self.assertIsNone(Item.objects.create(name="Glue", measurement_unit=self.unit).for_sale)
        item.for_sale = False
        with self.assertRaises(ValidationError):
            item.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.filter(pk=item.pk).update(for_sale=False)

    def test_stock_or_unique_items_never_both(self):
        with self.assertRaises(ValidationError):
            ItemLocation(item=self.extinguisher, location=self.location, amount=1).full_clean()
        with self.assertRaises(ValidationError):
            UniqueItem(item=self.item, location=self.location).full_clean()

    def test_kind_is_fixed_while_used(self):
        self.extinguisher.kind = Item.Kind.BULK
        with self.assertRaises(ValidationError) as raised:
            self.extinguisher.full_clean()
        self.assertIn("kind", raised.exception.message_dict)
        self.other_item.kind = Item.Kind.UNIQUE
        self.other_item.full_clean()

    def test_located_unless_disposed(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            UniqueItem.objects.create(item=self.extinguisher)
        with self.assertRaises(ValidationError):
            UniqueItem(item=self.extinguisher).full_clean()

    def test_usage_level_falls_back_to_the_type(self):
        self.assertEqual(self.unique_item.effective_usage_level, UsageLevel.GREEN)
        self.unique_item.usage_level = UsageLevel.RED
        self.assertEqual(self.unique_item.get_effective_usage_level_display(), "red")

    def test_owner_account_or_details(self):
        unique_item = UniqueItem(item=self.extinguisher, location=self.location, owner_user=self.owner, owner_first_name="Robin")
        with self.assertRaises(ValidationError):
            unique_item.full_clean()
        self.assertFalse(self.unique_item.has_owner)

    def test_history_records_who_moved_and_disposed(self):
        with acting_as(self.member):
            unique_item = UniqueItem.objects.create(item=self.extinguisher, location=self.location)
            unique_item.location = self.shelf
            unique_item.save()
        with acting_as(self.insider):
            unique_item.dispose(UniqueItem.DisposalReason.SCRAPPED, "pressure lost")
        disposed, moved, created = unique_item.events.all()
        self.assertEqual((created.type, created.actor, created.to_location_name),
                         (UniqueItemEvent.Type.CREATED, self.member, str(self.location)))
        self.assertEqual((moved.type, moved.from_location, moved.to_location),
                         (UniqueItemEvent.Type.MOVED, self.location, self.shelf))
        self.assertEqual((disposed.type, disposed.actor, disposed.from_location, disposed.reason, disposed.note),
                         (UniqueItemEvent.Type.DISPOSED, self.insider, self.shelf, "scrapped", "pressure lost"))
        self.assertIsNone(UniqueItem.objects.get(pk=unique_item.pk).location)
        self.assertFalse(UniqueItem.active.filter(pk=unique_item.pk).exists())

    def test_disposal_keeps_the_id(self):
        self.unique_item.dispose(UniqueItem.DisposalReason.LOST)
        self.assertEqual(LabelId.objects.get(pk=self.lid.pk).status, LabelId.Status.ASSIGNED)
        self.assertEqual(str(self.unique_item), "Fire extinguisher K7R-4XD")
        with self.assertRaises(services.LabelIdError):
            services.claim(make_id("12345").code, self.unique_item, None)


@override_settings(**SETTINGS)
class UniqueItemViewTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.unique_item.responsible_team = cls.team
        cls.unique_item.responsible_user = cls.member
        cls.unique_item.owner_user = cls.owner
        cls.unique_item.purchase_price = Decimal("123.45")
        cls.unique_item.notes = "See [manual](https://example.org/manual)"
        cls.unique_item.save()
        cls.extinguisher.last_purchase_price = Decimal("99.00")
        cls.extinguisher.save()

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def create_data(self, **extra):
        return {
            "item": self.extinguisher.pk, "location": self.location.pk, "label_choice": "generate",
            "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0", "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0", **extra,
        }

    def test_public_page_shows_first_names_and_team_only(self):
        response = self.client.get(self.unique_item.get_absolute_url())
        self.assertContains(response, "K7R-4XD")
        # No label section: labels are printed with the print dialog's templates
        self.assertNotContains(response, "/print/templates/")
        self.assertContains(response, "Woodworking")
        self.assertContains(response, "Alex")
        self.assertContains(response, "Not ZAM property: Robin")
        self.assertContains(response, '<a href="https://example.org/manual" rel="nofollow noopener noreferrer">manual</a>', html=True)
        for internal in ("Example", "alex@example.org", "Private", "robin@example.org", "123.45", "99.00"):
            self.assertNotContains(response, internal)

    def test_hidden_internal_details_are_marked(self):
        chip = '<span class="unique-item-internal" title="Only visible with the permission for internal details.">internal</span>'
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        # Responsible person, owner details (also in the history) and purchase price are recorded but internal.
        self.assertEqual(content.count(chip), 4)
        self.assertInHTML(f"<dt>Purchase price</dt><dd>{chip}</dd>", content)
        self.assertInHTML(f"<dd>{chip}</dd>", self.client.get(self.extinguisher.get_absolute_url()).content.decode())
        self.client.force_login(self.insider)
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        self.assertInHTML(f"<dt>Purchase price</dt><dd>123.45 € {chip}</dd>", content)
        self.assertEqual(content.count(chip), 1)
        # Nothing internal recorded: no chip, except for the earlier owner account in the history.
        self.unique_item.responsible_user = self.unique_item.owner_user = self.unique_item.purchase_price = None
        self.unique_item.save()
        self.client.logout()
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        details, history = content.split('id="unique-item-history-heading"')
        self.assertNotIn(chip, details)
        self.assertIn("Owner changed: Robin → ZAM", history)

    def test_internal_details_with_permission(self):
        self.client.force_login(self.insider)
        response = self.client.get(self.unique_item.get_absolute_url())
        for internal in ("Alex Example", "alex@example.org", "Robin Private", "robin@example.org", "123.45"):
            self.assertContains(response, internal)
        self.assertContains(self.client.get(self.extinguisher.get_absolute_url()), "99.00")

    def test_zam_property_shows_no_owner(self):
        self.unique_item.owner_user = None
        self.unique_item.save()
        self.assertNotContains(self.client.get(self.unique_item.get_absolute_url()), "Not ZAM property")

    def test_label_of_assigned_id_is_public(self):
        response = self.client.get(label_preview_url(self.lid))
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/png"))
        reserved = make_id("ABCDE")
        self.assertEqual(self.client.get(label_preview_url(reserved)).status_code, 404)
        self.client.force_login(self.member)  # may print labels
        self.assertEqual(self.client.get(label_preview_url(reserved)).status_code, 200)

    def test_create_generates_an_id(self):
        self.client.force_login(self.member)
        before = LabelId.objects.count()
        response = self.client.post(reverse("create_unique_item"), self.create_data(owner_first_name="Kim"))
        unique_item = UniqueItem.objects.latest("pk")
        self.assertRedirects(response, unique_item.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(LabelId.objects.count(), before + 1)
        lid = LabelId.objects.get(unique_item=unique_item)
        self.assertEqual((lid.status, lid.assigned_by, lid.batch), (LabelId.Status.ASSIGNED, self.member, "unique_item"))
        self.assertEqual(unique_item.events.get().actor, self.member)
        self.assertEqual(unique_item.owner_first_name, "Kim")

    def test_create_with_a_reserved_label(self):
        self.client.force_login(self.member)
        reserved = make_id("ABCDE")
        response = self.client.post(reverse("create_unique_item"), self.create_data(
            label_choice="reserved", label_code=f"https://i.zam.haus/{reserved.code}"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LabelId.objects.get(pk=reserved.pk).unique_item, UniqueItem.objects.latest("pk"))

    def test_used_label_saves_nothing(self):
        self.client.force_login(self.member)
        count = UniqueItem.objects.count()
        response = self.client.post(reverse("create_unique_item"), self.create_data(
            label_choice="reserved", label_code=self.lid.code))
        self.assertEqual(response.status_code, 200)
        self.assertIn("label_code", response.context["form"].errors)
        self.assertEqual(UniqueItem.objects.count(), count)

    def test_claim_race_rolls_back(self):
        self.client.force_login(self.member)
        reserved = make_id("ABCDE")
        count = UniqueItem.objects.count()
        original = services.claim

        def claim_taken(code, target, user):
            services.claim = original
            raise services.LabelIdError("The ID is already in use.")
        services.claim = claim_taken
        self.addCleanup(setattr, services, "claim", original)
        response = self.client.post(reverse("create_unique_item"), self.create_data(label_choice="reserved", label_code=reserved.code))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UniqueItem.objects.count(), count)
        self.assertEqual(UniqueItemEvent.objects.filter(unique_item__pk__gt=self.unique_item.pk).count(), 0)

    def test_creating_needs_claim_permission(self):
        user = get_user_model().objects.create_user(username="adder")
        grant(user, "add_uniqueitem")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("create_unique_item")).status_code, 403)

    def test_internal_fields_are_not_rendered_or_changed_without_permission(self):
        self.client.force_login(self.member)
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        response = self.client.get(url)
        for name in ("purchase_price", "owner_user", "owner_contact", "responsible_user"):
            self.assertNotIn(name, response.context["form"].fields)
        self.assertNotContains(response, "Robin")
        data = {"location": self.shelf.pk, "purchase_price": "1.00", "owner_first_name": "",
                "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0", "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        unique_item = UniqueItem.objects.get(pk=self.unique_item.pk)
        self.assertEqual((unique_item.location, unique_item.purchase_price, unique_item.owner_user), (self.shelf, Decimal("123.45"), self.owner))
        moved = unique_item.events.get(type=UniqueItemEvent.Type.MOVED)
        self.assertEqual((moved.actor, moved.to_location), (self.member, self.shelf))

    def test_files_are_attached(self):
        self.client.force_login(self.member)
        data = {"location": self.location.pk, "files-TOTAL_FORMS": "1", "files-INITIAL_FORMS": "0", "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0",
                "files-0-description": "Test certificate", "files-0-level": "unique",
                "files-0-file": SimpleUploadedFile("certificate.pdf", b"%PDF-1.4", content_type="application/pdf")}
        self.assertEqual(self.client.post(reverse("update_unique_item", args=[self.unique_item.pk]), data).status_code, 302)
        self.assertContains(self.client.get(self.unique_item.get_absolute_url()), "Test certificate")

    def test_user_autocomplete_needs_internal_permission(self):
        url = reverse("user_autocomplete")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.insider)
        self.assertContains(self.client.get(url, {"q": "rob"}), "Robin Private (owner)")

    def test_dispose(self):
        url = reverse("dispose_unique_item", args=[self.unique_item.pk])
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, {"reason": "scrapped"}).status_code, 403)
        self.client.force_login(self.insider)
        response = self.client.post(url, {"reason": "scrapped", "note": "empty"})
        self.assertRedirects(response, self.location.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(list(self.client.get(self.location.get_absolute_url()).context["unique_items"]), [])
        # The old label still leads to the unique item's page, which explains what happened.
        response = self.client.get(reverse("label_id_resolve", args=[self.lid.code]))
        self.assertRedirects(response, self.unique_item.get_absolute_url(), fetch_redirect_response=False)
        self.assertContains(self.client.get(self.unique_item.get_absolute_url()), "Removed from the inventory")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_location_and_item_pages_list_unique_items(self):
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, "K7R-4XD")
        self.assertContains(response, self.unique_item.get_absolute_url())
        response = self.client.get(self.extinguisher.get_absolute_url())
        self.assertContains(response, "K7R-4XD")
        self.assertEqual(len(response.context["unique_items"]), 1)

    def test_item_search_offers_a_new_item_last(self):
        url = reverse("unique_kind_item_autocomplete")
        self.client.force_login(self.member)
        results = self.client.get(url, {"q": "Ladder"}).json()["results"]
        self.assertEqual(results[-1], {"id": "new:Ladder", "text": "Create new item “Ladder”"})
        self.assertNotIn("new:", self.client.get(url, {"q": "fire extinguisher"}).json()["results"][-1]["id"])
        # Nothing is created by searching; the item is created with its unique item.
        self.assertEqual(self.client.post(url, {"text": "Ladder"}).status_code, 405)
        self.assertFalse(Item.objects.filter(name="Ladder").exists())
        visitor = get_user_model().objects.create_user(username="visitor")
        self.client.force_login(visitor)
        self.assertEqual(self.client.get(url, {"q": "Bench"}).json()["results"], [])

    def test_new_item_alongside_a_new_unique_item(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("create_unique_item"), self.create_data(item="new:  Ladder   3 m "))
        ladder = Item.objects.get(name="Ladder 3 m")
        unique_item = ladder.unique_items.get()
        self.assertRedirects(response, unique_item.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((ladder.kind, unique_item.location), (Item.Kind.UNIQUE, self.location))
        self.assertTrue(LabelId.objects.filter(unique_item=unique_item, status=LabelId.Status.ASSIGNED).exists())

    def test_new_item_is_only_created_with_the_unique_item(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("create_unique_item"), self.create_data(item="new:Ladder", location=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(name="Ladder").exists())
        # The choice survives the error, without listing every other item.
        self.assertContains(response, '<option value="new:Ladder" selected>New item “Ladder”</option>', html=True)
        self.assertNotContains(response, f'<option value="{self.extinguisher.pk}"')

    def test_new_item_needs_permission(self):
        user = get_user_model().objects.create_user(username="adder")
        grant(user, "add_uniqueitem", "claim_labelid")
        self.client.force_login(user)
        response = self.client.post(reverse("create_unique_item"), self.create_data(item="new:Ladder"))
        self.assertIn("item", response.context["form"].errors)
        self.assertFalse(Item.objects.filter(name="Ladder").exists())

    def test_breadcrumbs(self):
        response = self.client.get(self.unique_item.get_absolute_url())
        self.assertContains(response, f'<a href="{reverse("index_items")}">Items</a>', html=True)
        self.assertContains(response, f'<a href="{self.extinguisher.get_absolute_url()}">Fire extinguisher</a>', html=True)
        self.assertContains(response, f'<a href="{self.unique_item.get_absolute_url()}" aria-current="page">K7R-4XD</a>', html=True)
        drawer = Location.objects.create(name="Drawer", short_name="D2", type=self.kind, parent_location=self.shelf)
        response = self.client.get(drawer.get_absolute_url())
        content = response.content.decode()
        for location in (self.location, self.shelf):
            self.assertInHTML(f'<a href="{location.get_absolute_url()}">{location.name} [{location.short_name}]</a>', content)
        self.assertInHTML(f'<a href="{drawer.get_absolute_url()}" aria-current="page">Drawer [D2]</a>', content)
        self.assertLess(content.index("Workshop [WS]</a>"), content.index("Shelf [S]</a>"))
        self.assertNotIn(f">{drawer.locatable_identifier}</a>", content)

    def test_search_by_id_opens_the_unique_item(self):
        response = self.client.get(reverse("index_items"), {"q": "k7r-4xd"}, follow=True)
        self.assertEqual(response.redirect_chain[-1][0], self.unique_item.get_absolute_url())

    def new_item_data(self, kind="unique", **first):
        data = {"kind": kind, "name": "Circular saw", "description": "", "usage_level": "red", "barcode_data": "",
                "measurement_unit": self.unit.pk,
                "itemlocation_set-TOTAL_FORMS": "1", "itemlocation_set-INITIAL_FORMS": "0",
                "itemimage_set-TOTAL_FORMS": "0", "itemimage_set-INITIAL_FORMS": "0",
                "itemfile_set-TOTAL_FORMS": "0", "itemfile_set-INITIAL_FORMS": "0",
                "first_unique_item-TOTAL_FORMS": "1", "first_unique_item-INITIAL_FORMS": "0",
                "first_unique_item-0-label_choice": "generate"}
        data.update({f"first_unique_item-0-{key}": value for key, value in first.items()})
        return data

    def test_new_item_comes_with_its_first_unique_item(self):
        self.client.force_login(self.member)
        url = reverse("create_item") + f"?kind=unique&location_id={self.shelf.pk}"
        response = self.client.get(url)
        self.assertRegex(response.content.decode(), r'name="kind" value="unique"[^>]*checked')
        inlines = response.context["inlines"]
        self.assertEqual([inline.prefix for inline in inlines],
                         ["itemimage_set", "itemfile_set", "itemlocation_set", "first_unique_item"])
        form = inlines[3]
        self.assertEqual((len(form.forms), form.forms[0]["location"].value()), (1, self.shelf.pk))
        response = self.client.post(url, self.new_item_data(location=self.shelf.pk))
        self.assertEqual(response.status_code, 302, response.context and ([i.errors for i in response.context["inlines"]], [i.non_form_errors() for i in response.context["inlines"]], response.context["form"].errors))
        saw = Item.objects.get(name="Circular saw")
        self.assertEqual((saw.kind, saw.usage_level, saw.itemlocation_set.count()), (Item.Kind.UNIQUE, "red", 0))
        first = saw.unique_items.get()
        self.assertRedirects(response, first.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((first.location, LabelId.objects.get(unique_item=first).status), (self.shelf, LabelId.Status.ASSIGNED))
        self.assertEqual(first.events.get().actor, self.member)

    def test_new_item_needs_a_location_and_a_valid_label(self):
        self.client.force_login(self.member)
        url = reverse("create_item") + "?kind=unique"
        response = self.client.post(url, self.new_item_data(location=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn("location", response.context["inlines"][3].forms[0].errors)
        response = self.client.post(url, self.new_item_data(location=self.shelf.pk, label_choice="reserved", label_code=self.lid.code))
        self.assertIn("label_code", response.context["inlines"][3].forms[0].errors)
        self.assertFalse(Item.objects.filter(name="Circular saw").exists())
        reserved = make_id("ABCDE")
        self.client.post(url, self.new_item_data(location=self.shelf.pk, label_choice="reserved", label_code=reserved.code))
        self.assertEqual(LabelId.objects.get(pk=reserved.pk).unique_item.item.name, "Circular saw")

    def test_new_item_with_unique_items_needs_their_permissions(self):
        user = get_user_model().objects.create_user(username="adder")
        grant(user, "add_item")
        self.client.force_login(user)
        response = self.client.get(reverse("create_item") + "?kind=unique")
        self.assertEqual([value for value, _label in response.context["form"].fields["kind"].choices], ["bulk"])
        self.assertEqual(self.client.post(reverse("create_item"), self.new_item_data(kind="unique")).status_code, 403)
        self.assertFalse(Item.objects.filter(name="Circular saw").exists())

    def test_switching_the_kind_keeps_and_ignores_the_other_part(self):
        self.client.force_login(self.member)
        url = reverse("create_item") + f"?location_id={self.shelf.pk}"
        data = {**self.new_item_data(location=""), "itemlocation_set-0-location": self.shelf.pk,
                "itemlocation_set-0-amount": "5"}
        # Chosen as bulk item: the (incomplete) first unique item is ignored.
        response = self.client.post(url, {**data, "kind": "bulk"})
        # Created from a location: back to that location.
        self.assertRedirects(response, self.shelf.get_absolute_url(), fetch_redirect_response=False)
        saw = Item.objects.get(name="Circular saw")
        self.assertEqual((saw.kind, saw.usage_level, saw.unique_items.count(), saw.itemlocation_set.get().amount),
                         (Item.Kind.BULK, "", 0, 5))
        # Chosen as unique items: the stock entry is ignored; an error shows both parts with their values.
        response = self.client.post(url, {**data, "kind": "unique", "name": "Ladder"})
        self.assertEqual(response.status_code, 200)
        inlines = {inline.prefix: inline for inline in response.context["inlines"]}
        self.assertIn("location", inlines["first_unique_item"].forms[0].errors)
        self.assertEqual(inlines["itemlocation_set"].forms[0]["amount"].value(), "5")
        self.assertContains(response, 'data-for-kind="unique"')
        self.assertFalse(Item.objects.filter(name="Ladder").exists())

    def test_kind_cannot_change_with_unique_items(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("update_item", args=[self.extinguisher.pk]))
        self.assertTrue(response.context["form"].fields["kind"].disabled)


@override_settings(**SETTINGS)
class UniqueItemLocationTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        LocationType.objects.filter(pk=cls.kind.pk).update(deletable_in_frontend=True)
        cls.admin = get_user_model().objects.create_user(username="admin")
        grant(cls.admin, "delete_location", "change_location", "delete_itemlocation", "change_itemlocation",
              "dispose_uniqueitem")

    def test_location_with_unique_items_cannot_be_deleted(self):
        with self.assertRaises(ValidationError):
            self.location.delete()
        self.unique_item.dispose(UniqueItem.DisposalReason.OTHER)
        self.shelf.delete()
        Location.objects.get(pk=self.location.pk).delete()
        self.assertTrue(Location.objects.get(pk=self.location.pk).is_deleted)

    def test_dissolution_is_blocked_by_unique_items(self):
        self.client.force_login(self.admin)
        url = reverse("location_dissolve", args=[self.location.pk])
        response = self.client.get(url)
        self.assertContains(response, "Unique items must be handled one by one first")
        self.assertContains(response, reverse("dispose_unique_item", args=[self.unique_item.pk]))
        response = self.client.post(url, {"recursive": "0", f"location_{self.shelf.pk}_delete": "on"})
        self.assertNotIn("plan_token", response.context)
        self.assertTrue(Location.active.filter(pk=self.location.pk).exists())

    def test_deleting_a_sub_location_with_unique_items_is_blocked(self):
        unique_item = UniqueItem.objects.create(item=self.extinguisher, location=self.shelf)
        self.unique_item.dispose(UniqueItem.DisposalReason.OTHER)
        self.client.force_login(self.admin)
        url = reverse("location_dissolve", args=[self.location.pk])
        response = self.client.post(url, {"recursive": "0", f"location_{self.shelf.pk}_delete": "on"})
        self.assertNotIn("plan_token", response.context)
        self.assertContains(response, "still contains unique items")
        # Moving the sub-location keeps its unique items together.
        response = self.client.post(url, {"recursive": "0", f"location_{self.shelf.pk}_destination": self.other_location().pk})
        self.assertIn("plan_token", response.context)
        response = self.client.post(url, {"stage": "confirm", "plan": response.context["plan_token"]})
        self.assertEqual(UniqueItem.objects.get(pk=unique_item.pk).location, self.shelf)
        self.assertFalse(Location.active.filter(pk=self.location.pk).exists())

    def other_location(self):
        return Location.objects.create(name="Storage", short_name="ST", type=self.kind)

    def test_missing_ids_are_reported(self):
        services.retire(self.lid.code, None)
        out = StringIO()
        call_command("label_id_check", "--missing", stdout=out)
        self.assertIn(f"unique item #{self.unique_item.pk}", out.getvalue())


@override_settings(**SETTINGS)
class UniqueItemAdminTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.admin = get_user_model().objects.create_superuser(username="admin")

    def add(self, query=""):
        self.client.force_login(self.admin)
        data = {"item": self.extinguisher.pk, "location": self.location.pk, "usage_level": "",
                "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0", "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0",
                "events-TOTAL_FORMS": "0", "events-INITIAL_FORMS": "0"}
        response = self.client.post(reverse("admin:inventory_uniqueitem_add") + query, data)
        self.assertEqual(response.status_code, 302, response.context and response.context.get("errors"))
        return UniqueItem.objects.latest("pk")

    def test_admin_add_generates_an_id(self):
        unique_item = self.add()
        self.assertEqual(LabelId.objects.get(unique_item=unique_item).status, LabelId.Status.ASSIGNED)

    def test_admin_add_claims_the_scanned_label(self):
        reserved = make_id("ABCDE")
        unique_item = self.add(f"?label_id={reserved.code}")
        self.assertEqual(LabelId.objects.get(pk=reserved.pk).unique_item, unique_item)


class ForSaleMigrationTests(TransactionTestCase):
    def test_priced_items_become_for_sale(self):
        before = [("inventory", "0022_zamid_triggers_and_claim")]
        after = [("inventory", "0023_unique_items_squashed_0031")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            Item = apps.get_model("inventory", "Item")
            unit = apps.get_model("inventory", "MeasurementUnit").objects.create(name="Piece", short="pc")
            priced = Item.objects.create(name="Priced", sale_price=Decimal("1.50"), measurement_unit=unit)
            unpriced = Item.objects.create(name="Unpriced", measurement_unit=unit)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            Item = executor.loader.project_state(after).apps.get_model("inventory", "Item")
            self.assertEqual(dict(Item.objects.values_list("pk", "for_sale")), {priced.pk: True, unpriced.pk: None})
            self.assertEqual(set(Item.objects.values_list("kind", flat=True)), {"bulk"})
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())


@override_settings(**SETTINGS)
class OwnerChangeTests(UniqueItemFixture, TestCase):
    """The owner is set when a unique item is created; later only admins or with the permission."""

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.unique_item.owner_first_name = "Robin"
        cls.unique_item.save()

    def update(self, user, **data):
        self.client.force_login(user)
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        return self.client.post(url, {"location": self.location.pk, "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0",
                                      "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0", **data})

    def test_members_cannot_change_the_owner_later(self):
        self.client.force_login(self.member)
        form = self.client.get(reverse("update_unique_item", args=[self.unique_item.pk])).context["form"]
        self.assertTrue(form.fields["owner_first_name"].disabled)
        self.assertEqual(self.update(self.member, owner_first_name="Mallory", notes="still editable").status_code, 302)
        self.unique_item.refresh_from_db()
        self.assertEqual((self.unique_item.owner_first_name, self.unique_item.notes), ("Robin", "still editable"))

    def test_with_permission_or_as_admin(self):
        grant(self.member, "change_uniqueitem_owner")
        self.update(self.member, owner_first_name="Kim")
        self.unique_item.refresh_from_db()
        self.assertEqual(self.unique_item.owner_first_name, "Kim")
        admin = get_user_model().objects.create_superuser(username="admin")
        self.update(admin, owner_first_name="", owner_user=self.owner.pk)
        self.unique_item.refresh_from_db()
        self.assertEqual((self.unique_item.owner_first_name, self.unique_item.owner_user), ("", self.owner))

    def test_owner_changes_are_recorded(self):
        # Owner accounts are internal details.
        grant(self.insider, "change_uniqueitem_owner", "change_uniqueitem")
        self.update(self.insider, owner_first_name="", owner_user=self.owner.pk, notes="handed over")
        self.update(self.insider, owner_user="", notes="donated to the ZAM")
        to_zam, to_account, initial = self.unique_item.events.filter(type=UniqueItemEvent.Type.OWNER_CHANGED)
        self.assertEqual((to_account.actor, to_account.from_owner_name, to_account.from_owner_user,
                          to_account.to_owner_name, to_account.to_owner_user),
                         (self.insider, "Robin", None, "Robin", self.owner))
        self.assertEqual((to_zam.from_owner_user, to_zam.from_owner_label, to_zam.to_owner_label),
                         (self.owner, "Robin", "ZAM"))
        # Set in setUpTestData, without an actor.
        self.assertEqual((initial.from_owner_label, initial.to_owner_label, initial.actor), ("ZAM", "Robin", None))
        # Edits without an owner change add no owner entry.
        self.update(self.insider, notes="just notes")
        self.assertEqual(self.unique_item.events.filter(type=UniqueItemEvent.Type.OWNER_CHANGED).count(), 3)

    def test_owner_history_on_the_page(self):
        self.unique_item.owner_first_name, self.unique_item.owner_contact = "", "Kim Sample, kim@example.org"
        self.unique_item.save()
        page = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        self.assertIn("Owner changed: Robin → someone else", page)
        self.assertNotIn("kim@example.org", page)
        self.assertIn('class="unique-item-internal"', page)
        self.client.force_login(self.insider)
        self.assertContains(self.client.get(self.unique_item.get_absolute_url()), "after: Kim Sample, kim@example.org")

    def test_initial_owner_is_part_of_the_creation_entry(self):
        unique_item = UniqueItem.objects.create(item=self.extinguisher, location=self.location, owner_user=self.owner)
        created = unique_item.events.get()
        self.assertEqual((created.type, created.to_owner_user, created.to_owner_name),
                         (UniqueItemEvent.Type.CREATED, self.owner, "Robin"))
        self.assertContains(self.client.get(unique_item.get_absolute_url()), "Owner: Robin")
        self.assertFalse(self.unique_item.events.get(type=UniqueItemEvent.Type.CREATED).has_to_owner)

    def test_owner_accounts_cannot_be_deleted_silently(self):
        self.unique_item.owner_first_name, self.unique_item.owner_user = "", self.owner
        self.unique_item.save()
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_owner_is_free_when_creating(self):
        self.client.force_login(self.member)
        form = self.client.get(reverse("create_unique_item")).context["form"]
        self.assertFalse(form.fields["owner_first_name"].disabled)

    def test_admin_shows_owner_read_only_without_permission(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        grant(staff, "view_uniqueitem", "change_uniqueitem")
        self.client.force_login(staff)
        response = self.client.get(reverse("admin:inventory_uniqueitem_change", args=[self.unique_item.pk]))
        self.assertNotContains(response, 'name="owner_first_name"')
        self.assertContains(response, "Robin")


@override_settings(**SETTINGS)
class InternalFieldsOnCreationTests(UniqueItemFixture, TestCase):
    """Owner and responsible person accounts, owner contact and price need the permission for internal details."""

    INTERNAL = ("owner_user", "responsible_user", "owner_contact", "purchase_price")

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def create(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("create_unique_item"), {
            "item": self.extinguisher.pk, "location": self.location.pk, "label_choice": "generate",
            "owner_user": self.owner.pk, "responsible_user": self.member.pk, "purchase_price": "10.00",
            "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0", "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0",
            **data})

    def test_not_offered_or_saved_without_permission(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("create_unique_item"))
        for name in self.INTERNAL:
            self.assertNotIn(name, response.context["form"].fields)
            self.assertNotContains(response, f'name="{name}"')
        self.assertEqual(self.create(self.member, owner_first_name="Kim", owner_contact="Phone 123").status_code, 302)
        created = UniqueItem.objects.latest("pk")
        self.assertEqual((created.owner_user, created.responsible_user, created.owner_contact, created.purchase_price),
                         (None, None, "", None))
        self.assertEqual(created.owner_first_name, "Kim")  # first names are public

    def test_offered_and_saved_with_permission(self):
        self.client.force_login(self.insider)
        response = self.client.get(reverse("create_unique_item"))
        for name in self.INTERNAL:
            self.assertIn(name, response.context["form"].fields)
        self.assertEqual(self.create(self.insider).status_code, 302)
        created = UniqueItem.objects.latest("pk")
        self.assertEqual((created.owner_user, created.responsible_user, created.purchase_price),
                         (self.owner, self.member, Decimal("10.00")))

    def test_admin_without_permission(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        grant(staff, "view_uniqueitem", "add_uniqueitem", "change_uniqueitem")
        self.client.force_login(staff)
        for url in (reverse("admin:inventory_uniqueitem_add"), reverse("admin:inventory_uniqueitem_change", args=[self.unique_item.pk])):
            response = self.client.get(url)
            for name in self.INTERNAL:
                self.assertNotContains(response, f'name="{name}"')


@override_settings(**{**SETTINGS, "LANGUAGE_CODE": "de"})
class GermanCreatePageTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def test_kind_hints_are_translated(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("create_item"), HTTP_ACCEPT_LANGUAGE="de")
        self.assertContains(response, "Ein Mengenartikel wird pro Standort gezählt, etwa Schrauben oder Filament.")
        self.assertContains(response, "Einzelobjekte sind Gegenstände, die einzeln erfasst werden")
        self.assertNotContains(response, "A bulk item is counted per location")
