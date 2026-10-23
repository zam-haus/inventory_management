from html.parser import HTMLParser
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ..admin import LocationInline, StockChangeInline
from ..models import Item, Location, LocationType, MeasurementUnit, StockChange


class FormData(HTMLParser):
    """Collect what a browser would submit for the change form."""

    def __init__(self):
        super().__init__()
        self.data, self.select, self.multiple, self.textarea = {}, None, False, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get("name")
        if tag == "input" and name and "__prefix__" not in name:
            if attrs.get("type") in ("checkbox", "radio"):
                if "checked" in attrs:
                    self.data[name] = attrs.get("value", "on")
            elif attrs.get("type") not in ("submit", "file"):
                self.data[name] = attrs.get("value", "")
        elif tag == "select" and name and "__prefix__" not in name:
            # A multiple select without a selected option is not submitted at all.
            self.select, self.multiple = name, "multiple" in attrs
            if not self.multiple:
                self.data.setdefault(name, "")
        elif tag == "option" and self.select and "selected" in attrs:
            if self.multiple:
                self.data.setdefault(self.select, []).append(attrs.get("value", ""))
            else:
                self.data[self.select] = attrs.get("value", "")
        elif tag == "textarea" and name and "__prefix__" not in name:
            self.textarea = name
            self.data[name] = ""

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        elif tag == "textarea":
            self.textarea = None

    def handle_data(self, data):
        if self.textarea:
            self.data[self.textarea] += data.removeprefix("\n")


def form_data(response):
    parser = FormData()
    parser.feed(response.content.decode())
    return parser.data


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ], LANGUAGE_CODE="en",
)
class CappedInlineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.box = LocationType.objects.create(name="Box", moveable=True)
        cls.parent = Location.objects.create(type=room, name="Storage", short_name="S")
        cls.user = get_user_model().objects.create_user(username="admin", is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def add_children(self, count):
        for i in range(count):
            Location.objects.create(type=self.box, name=f"Box {i:03}", short_name=f"B{i:03}", parent_location=self.parent)

    def change_url(self, obj):
        return reverse(f"admin:inventory_{obj._meta.model_name}_change", args=[obj.pk])

    def test_location_with_many_sub_locations_saves_within_the_field_limit(self):
        self.add_children(LocationInline.max_rows * 3)
        response = self.client.get(self.change_url(self.parent))
        data = form_data(response)
        self.assertLess(len(data), 1000)

        data["name"] = "Main storage"
        response = self.client.post(self.change_url(self.parent), data)

        self.assertRedirects(response, reverse("admin:inventory_location_changelist"))
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.name, "Main storage")
        self.assertEqual(self.parent.children.count(), LocationInline.max_rows * 3)

    def test_capped_inline_is_read_only_and_links_to_the_full_list(self):
        self.add_children(3)
        Location.objects.filter(name="Box 000").update(is_deleted=True)
        with mock.patch.object(LocationInline, "max_rows", 2):
            response = self.client.get(self.change_url(self.parent))

        formset = response.context["inline_admin_formsets"][0]
        self.assertEqual(len(formset.formset.forms), 2)
        self.assertFalse(formset.has_change_permission)
        self.assertFalse(formset.has_add_permission)
        self.assertFalse(formset.has_delete_permission)
        self.assertNotIn("children-0-name", form_data(response))
        self.assertContains(response, "Showing 2 of 3 entries, read-only.")

        full_list = formset.formset.full_list_url
        self.assertEqual(
            full_list,
            reverse("admin:inventory_location_changelist") + f"?parent_location__exact={self.parent.pk}&is_deleted__exact=all",
        )
        response = self.client.get(full_list)
        self.assertEqual(response.context["cl"].result_count, 3)

    def test_small_inline_stays_editable(self):
        self.add_children(2)
        response = self.client.get(self.change_url(self.parent))

        formset = response.context["inline_admin_formsets"][0]
        self.assertTrue(formset.has_change_permission)
        self.assertIn("children-0-name", form_data(response))
        self.assertNotContains(response, "capped-inline-note")

    def test_stock_log_shows_newest_changes_and_links_to_the_log(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Screws", measurement_unit=unit)
        for note in ("old", "middle", "new"):
            StockChange.objects.create(
                item=item, item_name=item.name, location_name="Storage", unit="pc",
                direction=StockChange.Direction.INCREASE, reason=StockChange.Reason.choices[0][0], note=note,
            )
        with mock.patch.object(StockChangeInline, "max_rows", 2):
            response = self.client.get(self.change_url(item))

        formset = next(f for f in response.context["inline_admin_formsets"] if f.opts.model is StockChange)
        self.assertEqual([form.instance.note for form in formset.formset.forms], ["new", "middle"])
        response = self.client.get(formset.formset.full_list_url)
        self.assertEqual(response.context["cl"].result_count, 3)
