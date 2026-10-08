from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Item, ItemLocation, Location, LocationType, MeasurementUnit, StockChange, stock_change
from .stock_log import stock_changes


def permissions(*codenames):
    return Permission.objects.filter(content_type__app_label="inventory", codename__in=codenames)


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class StockChangeDialogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unit = MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.shelf = Location.objects.create(type=room, name="Shelf", short_name="SH")
        cls.cabinet = Location.objects.create(type=room, name="Cabinet", short_name="CAB")
        User = get_user_model()
        cls.seller = User.objects.create_user(username="seller")
        cls.seller.user_permissions.add(*permissions("add_stockchange"))
        cls.reader = User.objects.create_user(username="reader")

    def setUp(self):
        self.client.force_login(self.seller)
        self.item = Item.objects.create(name="Resistor", sale_price=Decimal("0.25"))
        self.entry = ItemLocation.objects.create(item=self.item, location=self.shelf, amount=10)

    def set_amount(self, amount):
        # Without logging the change.
        ItemLocation.objects.filter(pk=self.entry.pk).update(amount=amount)
        self.entry.refresh_from_db()

    def url(self, entry=None):
        return reverse("stock_change", args=[(entry or self.entry).pk])

    def remove(self, entry=None, json=False, **data):
        data = {"direction": "decrease", "reason": "sale", "note": "", **data}
        headers = {"Accept": "application/json"} if json else {}
        return self.client.post(self.url(entry), data, headers=headers)

    def messages(self, response):
        return [str(message) for message in get_messages(response.wsgi_request)]

    def test_partial_removal_reduces_amount_and_logs(self):
        next_url = self.shelf.get_absolute_url()
        response = self.remove(amount="3", note="Workshop", next=next_url)
        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, 7)
        log = StockChange.objects.get()
        self.assertEqual(
            (log.item, log.location, log.actor, log.reason, log.note, log.source),
            (self.item, self.shelf, self.seller, "sale", "Workshop", StockChange.Source.DIALOG),
        )
        self.assertEqual((log.amount_before, log.amount_after, log.amount), (10, 7, 3))
        self.assertEqual((log.sale_value, log.is_estimate, log.entry_removed), (Decimal("0.75"), False, False))
        self.assertEqual(self.messages(response), ["Removed 3 pc of “Resistor” from SH."])

    def test_restock_increases_precise_amount(self):
        response = self.remove(direction="increase", reason="purchase", amount="5", complete="on", note="Order 17")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, 15)
        log = StockChange.objects.get()
        self.assertEqual((log.direction, log.reason, log.amount, log.amount_before, log.amount_after, log.entry_removed),
                         ("increase", "purchase", 5, 10, 15, False))
        self.assertEqual((log.sale_value, log.note), (Decimal("1.25"), "Order 17"))
        self.assertEqual(self.messages(response), ["Added 5 pc of “Resistor” to SH."])

    def test_restock_increases_estimate(self):
        self.set_amount(-20)
        self.remove(direction="increase", reason="donation", amount="7")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount_text, "~27 pc")
        log = StockChange.objects.get()
        self.assertEqual((log.direction, log.amount, log.amount_after, log.is_estimate), ("increase", 7, -27, False))

    def test_restock_needs_amount(self):
        response = self.remove(direction="increase", reason="purchase", json=True)
        self.assertEqual(response.json()["errors"]["amount"][0]["message"], "Enter the amount.")

    def test_reason_must_fit_direction(self):
        for direction, reason in (("increase", "sale"), ("decrease", "purchase"), ("decrease", "recount_found")):
            with self.subTest(direction=direction, reason=reason):
                response = self.remove(direction=direction, reason=reason, amount="1", json=True)
                self.assertEqual(response.json()["errors"]["reason"][0]["message"], "Choose a reason that fits the change.")
        self.assertFalse(StockChange.objects.exists())

    def test_cannot_remove_more_than_stored(self):
        response = self.remove(amount="11")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Only 10 pc are stored here.", status_code=400)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, 10)
        self.assertFalse(StockChange.objects.exists())

    def test_amount_and_reason_are_required(self):
        response = self.remove(json=True, reason="")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()["errors"]), {"amount", "reason"})
        response = self.remove(json=True, direction="", amount="1")
        self.assertEqual(set(response.json()["errors"]), {"direction"})
        response = self.remove(json=True, amount="0")
        self.assertEqual(response.json()["errors"]["amount"][0]["message"], "Enter an amount greater than zero.")
        self.assertFalse(StockChange.objects.exists())

    def test_complete_removal_keeps_item_with_other_stock(self):
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=-1)
        response = self.remove(complete="on", reason="destruction", next=self.item.get_absolute_url())
        self.assertRedirects(response, self.item.get_absolute_url(), fetch_redirect_response=False)
        self.assertFalse(ItemLocation.objects.filter(pk=self.entry.pk).exists())
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_deleted)
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.entry_removed, log.amount_after), (10, True, None))

    def test_removing_the_last_stock_deletes_the_item(self):
        # A precise zero elsewhere is no stock.
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=0)
        response = self.remove(amount="10", json=True, next=self.item.get_absolute_url())
        self.assertEqual(response.json(), {"ok": True, "url": reverse("index_items")})
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_deleted)
        self.assertEqual(self.messages(response), [
            "Removed 10 pc of “Resistor” from SH. No stock is left, so “Resistor” was deleted.",
        ])
        self.assertEqual(StockChange.objects.get().item, self.item)

    def test_removing_the_last_stock_from_the_location_page_stays_there(self):
        next_url = self.shelf.get_absolute_url()
        response = self.remove(complete="on", json=True, next=next_url)
        self.assertEqual(response.json(), {"ok": True, "url": next_url})
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_deleted)
        self.assertIn("No stock is left, so “Resistor” was deleted.", self.messages(response)[0])

    def test_retry_after_complete_removal_returns_to_location_page(self):
        request_id = str(uuid4())
        next_url = self.shelf.get_absolute_url()
        self.remove(amount="10", request_id=request_id, next=next_url)
        response = self.remove(amount="10", request_id=request_id, next=next_url, json=True)
        self.assertEqual(response.json(), {"ok": True, "url": next_url})

    def test_partial_removal_reduces_estimate(self):
        self.set_amount(-20)
        self.remove(amount="4")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount_text, "~16 pc")
        log = StockChange.objects.get()
        self.assertEqual((log.amount_before, log.amount_after, log.amount), (-20, -16, 4))
        self.assertFalse(log.is_estimate)
        self.assertEqual(log.sale_value, Decimal("1.00"))

    def test_removing_estimate_down_to_nothing_leaves_few(self):
        for removed in ("20", "35"):
            with self.subTest(removed=removed):
                self.set_amount(-20)
                self.remove(amount=removed)
                self.entry.refresh_from_db()
                self.assertEqual(self.entry.amount_text, "few pc")
        self.assertTrue(ItemLocation.objects.filter(pk=self.entry.pk).exists())
        self.assertFalse(Item.objects.get(pk=self.item.pk).is_deleted)

    def test_few_and_many_stay_unchanged(self):
        for amount in (-1, -9999):
            for direction, reason in (("decrease", "sale"), ("increase", "purchase")):
                with self.subTest(amount=amount, direction=direction):
                    self.set_amount(amount)
                    self.remove(direction=direction, reason=reason, amount="3")
                    self.entry.refresh_from_db()
                    self.assertEqual(self.entry.amount, amount)
        self.assertEqual(StockChange.objects.count(), 4)

    def test_partial_removal_of_unspecific_amount_requires_a_count(self):
        self.set_amount(-9999)
        response = self.remove(json=True)
        self.assertEqual(response.json()["errors"]["amount"][0]["message"], "Enter the amount.")

    def test_complete_removal_of_estimate_is_estimated(self):
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=1)
        self.set_amount(-20)
        response = self.remove(amount="20", complete="on")
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.is_estimate, log.sale_value), (20, True, Decimal("5.00")))
        self.assertEqual(self.messages(response), ["Removed ~20 pc of “Resistor” from SH."])

    def test_complete_removal_with_counted_amount_is_precise(self):
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=1)
        self.set_amount(-20)
        self.remove(amount="17", complete="on")
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.is_estimate), (17, False))

    def test_complete_removal_of_unknown_amount(self):
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=1)
        self.set_amount(-9999)
        response = self.remove(complete="on", reason="own_use")
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.sale_value, log.entry_removed), (None, None, True))
        self.assertEqual(self.messages(response), ["Removed everything of “Resistor” from SH."])

    def test_sale_value_unknown_without_price(self):
        self.item.sale_price = None
        self.item.save()
        self.remove(amount="2")
        self.assertIsNone(StockChange.objects.get().sale_value)

    def test_retried_submission_is_applied_once(self):
        request_id = str(uuid4())
        self.remove(amount="3", request_id=request_id)
        response = self.remove(amount="3", request_id=request_id, json=True)
        self.assertEqual(response.json()["ok"], True)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, 7)
        self.assertEqual(StockChange.objects.count(), 1)
        self.assertIn("This stock change was already saved.", self.messages(response))

    def test_retry_after_complete_removal_goes_to_item_search(self):
        request_id = str(uuid4())
        self.remove(amount="10", request_id=request_id)
        response = self.remove(amount="10", request_id=request_id, json=True)
        self.assertEqual(response.json(), {"ok": True, "url": reverse("index_items")})

    def test_unsafe_next_url_is_ignored(self):
        response = self.remove(amount="1", next="https://example.org/")
        self.assertRedirects(response, self.item.get_absolute_url(), fetch_redirect_response=False)

    def test_permission_required(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.remove(amount="1").status_code, 403)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.remove(amount="1").status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, 10)

    def test_zam_local_group_may_remove_stock(self):
        group = Group.objects.get(name="ZAM-local")
        self.assertTrue(group.permissions.filter(codename="add_stockchange").exists())
        self.assertFalse(group.permissions.filter(codename="view_stockchange").exists())

    def test_deleted_items_and_locations_cannot_be_removed(self):
        self.item.delete()
        self.assertEqual(self.remove(amount="1").status_code, 404)

    def test_quick_items_have_no_stock_dialog(self):
        quick = ItemLocation.objects.create(item=Item.objects.create(name="Glue"), location=self.cabinet, amount=None)
        self.assertEqual(self.client.get(self.url(quick)).status_code, 404)
        self.assertEqual(self.remove(quick, complete="on").status_code, 404)
        ItemLocation.objects.create(item=self.item, location=self.cabinet, amount=None)
        response = self.client.get(self.item.get_absolute_url())
        self.assertContains(response, self.url())
        self.assertNotContains(response, reverse("stock_change", args=[self.item.itemlocation_set.get(location=self.cabinet).pk]))

    def test_fallback_page(self):
        response = self.client.get(self.url() + "?next=" + self.shelf.get_absolute_url())
        self.assertContains(response, "Change stock")
        self.assertContains(response, 'name="request_id"')
        self.assertContains(response, f'value="{self.shelf.get_absolute_url()}"')
        self.assertContains(response, "This is the last stock of this item.")

    def test_buttons_only_with_permission(self):
        for page in (self.item.get_absolute_url(), self.shelf.get_absolute_url()):
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertContains(response, self.url())
                self.assertContains(response, 'id="stock-change"')
                self.assertContains(response, 'data-last-stock="true"')
                self.client.force_login(self.reader)
                self.assertNotContains(self.client.get(page), self.url())
                self.client.force_login(self.seller)

    def test_log_is_only_in_the_admin(self):
        self.remove(amount="1")
        admin = get_user_model().objects.create_superuser(username="admin")
        self.client.force_login(admin)
        log = StockChange.objects.get()
        self.assertContains(self.client.get(reverse("admin:inventory_stockchange_changelist")), "Resistor")
        detail = self.client.get(reverse("admin:inventory_stockchange_change", args=[log.pk]))
        self.assertContains(detail, "10 pc → 9 pc")
        self.assertContains(detail, "↓ −1 pc")
        self.assertNotContains(detail, 'name="_save"')
        self.assertContains(self.client.get(self.item.get_admin_url()), "10 pc → 9 pc")
        self.assertEqual(self.client.get(reverse("admin:inventory_stockchange_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:inventory_stockchange_delete", args=[log.pk])).status_code, 403)


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class AutomaticStockLogTests(TestCase):
    """Reductions outside the removal dialog are logged as well."""

    @classmethod
    def setUpTestData(cls):
        cls.unit = MeasurementUnit.objects.create(pk=1, name="Piece", short="pc")
        cls.room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.box = LocationType.objects.create(name="Box", moveable=True)
        cls.shelf = Location.objects.create(type=cls.room, name="Shelf", short_name="SH")
        cls.user = get_user_model().objects.create_superuser(username="admin")

    def setUp(self):
        self.client.force_login(self.user)
        self.item = Item.objects.create(name="Cable", sale_price=Decimal("2.00"))
        self.entry = ItemLocation.objects.create(item=self.item, location=self.shelf, amount=10)

    def test_reduction_rules(self):
        cases = [
            (Decimal(10), Decimal(7), ("decrease", 3, False)),
            (Decimal(10), Decimal(12), ("increase", 2, False)),
            (Decimal(10), Decimal(10), None),
            (Decimal(10), Decimal(-5), ("decrease", 5, True)),
            (Decimal(-5), Decimal(8), ("increase", 3, True)),
            (Decimal(-9999), Decimal(-1), ("decrease", None, True)),
            (Decimal(-1), Decimal(3), ("increase", None, True)),
            (Decimal(4), None, ("decrease", 4, False)),
            (Decimal(-8), None, ("decrease", 8, True)),
            (None, Decimal(3), None),
            (None, None, None),
        ]
        for before, after, expected in cases:
            with self.subTest(before=before, after=after):
                self.assertEqual(stock_change(before, after), expected)

    def test_unattributed_changes(self):
        self.entry.amount = 4
        self.entry.save()
        self.entry.amount = 6
        self.entry.save()
        decrease, increase = StockChange.objects.order_by("pk")
        self.assertEqual((decrease.direction, decrease.amount, decrease.reason, decrease.source, decrease.actor),
                         ("decrease", 6, "other", "other", None))
        self.assertEqual(decrease.sale_value, Decimal("12.00"))
        # Increases without a reason were found during a recount.
        self.assertEqual((increase.direction, increase.amount, increase.reason), ("increase", 2, "recount_found"))

    def test_item_form_reduction_is_a_recount(self):
        data = {
            "name": "Cable", "description": "", "measurement_unit": self.unit.pk, "barcode_data": "",
            "itemimage_set-TOTAL_FORMS": "0", "itemimage_set-INITIAL_FORMS": "0",
            "itemlocation_set-TOTAL_FORMS": "1", "itemlocation_set-INITIAL_FORMS": "1",
            "itemlocation_set-0-id": self.entry.pk, "itemlocation_set-0-item": self.item.pk,
            "itemlocation_set-0-location": self.shelf.pk, "itemlocation_set-0-amount": "8",
        }
        response = self.client.post(reverse("update_item", args=[self.item.pk]), data)
        self.assertEqual(response.status_code, 302)
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.reason, log.source, log.actor), (2, "recount_lost", "item_form", self.user))

    def test_admin_inline_deletion_is_logged(self):
        data = {
            "name": "Cable", "description": "", "measurement_unit": self.unit.pk, "sale_price": "2.00",
            "itembarcode_set-TOTAL_FORMS": "0", "itembarcode_set-INITIAL_FORMS": "0",
            "itemimage_set-TOTAL_FORMS": "0", "itemimage_set-INITIAL_FORMS": "0",
            "itemfile_set-TOTAL_FORMS": "0", "itemfile_set-INITIAL_FORMS": "0",
            "itemlocation_set-TOTAL_FORMS": "1", "itemlocation_set-INITIAL_FORMS": "1",
            "itemlocation_set-0-id": self.entry.pk, "itemlocation_set-0-item": self.item.pk,
            "itemlocation_set-0-location": self.shelf.pk, "itemlocation_set-0-amount": "10",
            "itemlocation_set-0-DELETE": "on",
            "stockchange_set-TOTAL_FORMS": "0", "stockchange_set-INITIAL_FORMS": "0",
        }
        response = self.client.post(self.item.get_admin_url(), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context.get("errors"))
        log = StockChange.objects.get()
        self.assertEqual((log.amount, log.entry_removed, log.reason, log.source), (10, True, "recount_lost", "admin"))

    def test_item_form_increase_is_found_in_recount(self):
        data = {
            "name": "Cable", "description": "", "measurement_unit": self.unit.pk, "barcode_data": "",
            "itemimage_set-TOTAL_FORMS": "0", "itemimage_set-INITIAL_FORMS": "0",
            "itemlocation_set-TOTAL_FORMS": "1", "itemlocation_set-INITIAL_FORMS": "1",
            "itemlocation_set-0-id": self.entry.pk, "itemlocation_set-0-item": self.item.pk,
            "itemlocation_set-0-location": self.shelf.pk, "itemlocation_set-0-amount": "13",
        }
        self.client.post(reverse("update_item", args=[self.item.pk]), data)
        log = StockChange.objects.get()
        self.assertEqual((log.direction, log.amount, log.reason, log.source), ("increase", 3, "recount_found", "item_form"))

    def test_moving_stock_is_not_a_change(self):
        cabinet = Location.objects.create(type=self.room, name="Cabinet", short_name="CAB")
        self.entry.location = cabinet
        self.entry.save()
        self.assertFalse(StockChange.objects.exists())

    def test_dissolution_deletion_is_logged(self):
        box = Location.objects.create(type=self.box, name="Box", short_name="B", parent_location=self.shelf)
        self.entry.location = box
        self.entry.save()
        url = reverse("location_dissolve", kwargs={"pk": box.pk})
        review = self.client.post(url, {"recursive": "0", "stage": "review", f"item_{self.entry.pk}_delete": "on"})
        self.client.post(url, {"stage": "confirm", "plan": review.context["plan_token"]})
        log = StockChange.objects.get()
        self.assertEqual((log.location, log.entry_removed, log.reason, log.source), (box, True, "other", "dissolution"))
        self.assertEqual(log.actor, self.user)

    def test_quick_items_are_not_logged(self):
        glue = ItemLocation.objects.create(item=Item.objects.create(name="Glue"), location=self.shelf, amount=None)
        tape = ItemLocation.objects.create(item=Item.objects.create(name="Tape"), location=self.shelf, amount=None)
        self.client.post(reverse("quick_item_delete", args=[glue.pk]))
        self.assertFalse(Item.objects.filter(name="Glue").exists())
        # Giving a quick-item an amount turns it into a regular item.
        tape.amount = -5
        tape.save()
        tape.delete()
        self.assertEqual(StockChange.objects.filter(item_name="Tape").count(), 1)
        self.assertFalse(StockChange.objects.filter(item_name="Glue").exists())

    def test_permanent_item_deletion_keeps_log_readable(self):
        with stock_changes(decrease_reason="other", source="admin", actor=self.user):
            self.entry.amount = 5
            self.entry.save()
            self.item.delete()
            self.item.delete()
        self.assertEqual(StockChange.objects.count(), 2)
        self.assertFalse(StockChange.objects.exclude(item=None).exists())
        self.assertEqual(set(StockChange.objects.values_list("item_name", flat=True)), {"Cable"})

    def test_logging_can_be_suppressed(self):
        with stock_changes(source="dialog", log=False):
            self.entry.amount = 1
            self.entry.save()
            self.entry.delete()
        self.assertFalse(StockChange.objects.exists())
