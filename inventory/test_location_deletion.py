from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .admin import LocationAdmin, LocationInlineFormSet
from .soft_delete_admin import DeletedObjectFilter
from .forms import DissolveLocationForm, ItemLocationForm, LocationMoveForm, PrintableInventoryForm
from .dissolution import DissolutionPlan
from .location_lookup import resolve_location_reference
from .models import Item, ItemLocation, Location, LocationType, MeasurementUnit


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class LocationSoftDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kind = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.parent = Location.objects.create(type=cls.kind, name="Parent", short_name="P")
        cls.archived = Location.objects.create(type=cls.kind, name="Archived room", short_name="OLD", parent_location=cls.parent)
        cls.live = Location.objects.create(type=cls.kind, name="Live room", short_name="NEW", parent_location=cls.parent)
        cls.archived.delete()
        cls.user = get_user_model().objects.create_user(username="reader", is_staff=True, is_superuser=True)
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Supply", measurement_unit=unit)

    def setUp(self):
        self.client.force_login(self.user)

    def test_rows_identifiers_and_parent_are_preserved(self):
        archived = Location.objects.get(pk=self.archived.pk)
        self.assertTrue(archived.is_deleted)
        self.assertEqual(archived.parent_location_id, self.parent.pk)
        self.assertEqual(archived.unique_identifier, "OLD")
        self.assertEqual(archived.locatable_identifier, "P.OLD")
        self.assertFalse(Location.active.filter(pk=archived.pk).exists())
        pk = archived.pk
        self.assertEqual(archived.delete()[0], 1)
        self.assertFalse(Location.objects.filter(pk=pk).exists())

    def test_nonempty_location_cannot_be_marked_deleted(self):
        with self.assertRaises(ValidationError):
            self.parent.delete()
        ItemLocation.objects.create(item=self.item, location=self.live, amount=2)
        with self.assertRaises(ValidationError):
            self.live.delete()
        self.assertTrue(Location.active.filter(pk=self.live.pk).exists())

    def test_bulk_delete_is_soft_and_children_are_processed_first(self):
        count, _details = Location.objects.filter(pk__in=[self.parent.pk, self.live.pk]).delete()
        self.assertEqual(count, 2)
        self.assertEqual(Location.objects.count(), 3)
        self.assertFalse(Location.active.exists())
        self.assertEqual(Location.objects.get(pk=self.archived.pk).parent_location_id, self.parent.pk)

    def test_bulk_delete_rolls_back_if_any_selected_location_is_nonempty(self):
        ItemLocation.objects.create(item=self.item, location=self.live, amount=2)
        empty = Location.objects.create(type=self.kind, name="Empty", short_name="EMPTY")
        with self.assertRaises(ValidationError):
            Location.objects.filter(pk__in=[self.parent.pk, self.live.pk, empty.pk]).delete()
        self.assertEqual(Location.active.count(), 3)
        self.assertFalse(Location.objects.get(pk=empty.pk).is_deleted)

    def test_archived_urls_are_unavailable(self):
        urls = [
            self.archived.get_absolute_url(),
            reverse("view_location2", args=[self.archived.pk]),
            reverse("location_move", args=[self.archived.pk]),
            reverse("locations_move_here", args=[self.archived.pk]),
            reverse("location_dissolve", args=[self.archived.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        for name in ("location_move", "locations_move_here", "location_dissolve"):
            self.assertEqual(self.client.post(reverse(name, args=[self.archived.pk]), {}).status_code, 404)

    def test_lists_children_and_autocomplete_hide_archived_records(self):
        for url in (reverse("index_locations"), self.parent.get_absolute_url()):
            response = self.client.get(url)
            self.assertNotContains(response, "Archived room")
            self.assertContains(response, "Live room")
        for name in ("location-autocomplete", "parent_location_autocomplete"):
            response = self.client.get(reverse(name), {"q": "Archived"})
            self.assertEqual(response.json()["results"], [])

    def test_archived_identifiers_and_urls_cannot_be_resolved(self):
        for value in ("OLD", "P.OLD", str(self.archived.pk), self.archived.get_absolute_url()):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                resolve_location_reference(value)

    def test_forms_reject_archived_destinations_and_print_roots(self):
        self.assertFalse(PrintableInventoryForm({"locations": [self.archived.pk]}).is_valid())
        form = ItemLocationForm({"location": self.archived.pk, "amount": 1})
        self.assertFalse(form.is_valid())
        self.assertNotIn(self.archived, LocationMoveForm().fields["parent_location"].queryset)
        form = DissolveLocationForm(plan=DissolutionPlan(self.parent))
        self.assertNotIn(self.archived, form.fields["bulk_destination"].queryset)
        self.assertEqual(len(form.rows), 1)
        response = self.client.post(reverse("locations_move_here", args=[self.live.pk]), {"identifiers": "OLD"}, follow=True)
        self.assertContains(response, "Locations moved: 0. Errors: 1.")

    def test_legacy_stock_at_archived_locations_is_hidden(self):
        # Even historical/manual associations must not leak archived locations.
        ItemLocation.objects.create(item=self.item, location=self.archived, amount=2)
        for url in (reverse("index_items"), self.item.get_absolute_url(), reverse("update_item", args=[self.item.pk]), reverse("annotate_item", args=[self.item.pk])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Archived room")
        report = self.client.get(reverse("print_inventory"), {"locations": self.parent.pk, "include_children": "1"})
        self.assertNotContains(report, "Supply")

    def test_archiving_a_destination_invalidates_a_pending_confirmation(self):
        destination = Location.objects.create(type=self.kind, name="Destination", short_name="DEST")
        url = reverse("location_dissolve", args=[self.parent.pk])
        review = self.client.post(url, {f"location_{self.live.pk}_destination": destination.pk})
        destination.delete()
        result = self.client.post(url, {"stage": "confirm", "plan": review.context["plan_token"]})
        self.assertContains(result, "The inventory changed")
        self.assertTrue(Location.active.filter(pk=self.parent.pk).exists())
        self.live.refresh_from_db()
        self.assertEqual(self.live.parent_location_id, self.parent.pk)

    def test_admin_can_inspect_deleted_records_and_offers_soft_deletion(self):
        request = RequestFactory().get("/")
        request.user = self.user
        model_admin = LocationAdmin(Location, admin.site)
        self.assertIn(self.archived, model_admin.get_queryset(request))
        self.assertTrue(model_admin.has_delete_permission(request, self.archived))
        self.assertIn(DeletedObjectFilter, model_admin.list_filter)

    def test_admin_default_filter_and_status_column(self):
        url = reverse("admin:inventory_location_changelist")
        response = self.client.get(url)
        self.assertNotIn(self.archived, response.context["cl"].result_list)
        self.assertIn(self.live, response.context["cl"].result_list)
        self.assertContains(response, '<td class="field-deleted_status"></td>', html=True)
        deleted = self.client.get(url, {"is_deleted__exact": "1"})
        self.assertEqual(list(deleted.context["cl"].result_list), [self.archived])
        self.assertContains(deleted, '<td class="field-deleted_status">❌</td>', html=True)
        all_records = self.client.get(url, {"is_deleted__exact": "all"})
        self.assertEqual(len(all_records.context["cl"].result_list), 3)

    def test_admin_delete_requires_confirmation_and_preserves_record(self):
        url = reverse("admin:inventory_location_delete", args=[self.live.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["protected"])
        self.assertTrue(Location.active.filter(pk=self.live.pk).exists())
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertTrue(Location.objects.get(pk=self.live.pk).is_deleted)

    def test_admin_delete_blocks_nonempty_locations(self):
        url = reverse("admin:inventory_location_delete", args=[self.parent.pk])
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["protected"])
        self.assertFalse(Location.objects.get(pk=self.parent.pk).is_deleted)

    def test_admin_bulk_delete_soft_deletes_selected_tree_after_confirmation(self):
        url = reverse("admin:inventory_location_changelist")
        data = {"action": "delete_selected", "_selected_action": [self.parent.pk, self.live.pk]}
        review = self.client.post(url, data)
        self.assertEqual(review.status_code, 200)
        self.assertFalse(review.context["protected"])
        self.assertEqual(Location.active.count(), 2)
        data["post"] = "yes"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Location.objects.count(), 3)
        self.assertFalse(Location.active.exists())

    def admin_change_data(self, location):
        return {
            "id": location.pk, "name": location.name, "short_name": location.short_name,
            "type": location.type_id, "parent_location": location.parent_location_id or "",
            "children-TOTAL_FORMS": "0", "children-INITIAL_FORMS": "0",
            "children-MIN_NUM_FORMS": "0", "children-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        }

    def test_admin_can_change_deleted_flag_and_restore(self):
        url = reverse("admin:inventory_location_change", args=[self.live.pk])
        page = self.client.get(url)
        self.assertContains(page, 'name="is_deleted"')
        data = self.admin_change_data(self.live)
        data["is_deleted"] = "on"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Location.objects.get(pk=self.live.pk).is_deleted)
        del data["is_deleted"]
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(Location.active.filter(pk=self.live.pk).exists())

    def test_admin_flag_cannot_delete_nonempty_location(self):
        ItemLocation.objects.create(item=self.item, location=self.live, amount=1)
        data = self.admin_change_data(self.live)
        data["is_deleted"] = "on"
        response = self.client.post(reverse("admin:inventory_location_change", args=[self.live.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The location is not empty and cannot be deleted.")
        self.assertTrue(Location.active.filter(pk=self.live.pk).exists())

    def test_restoring_child_requires_active_parent(self):
        self.live.delete()
        self.parent.delete()
        data = self.admin_change_data(self.live)
        response = self.client.post(reverse("admin:inventory_location_change", args=[self.live.pk]), data)
        self.assertContains(response, "Deleted locations cannot be used as destinations.")
        self.assertTrue(Location.objects.get(pk=self.live.pk).is_deleted)

    def test_inline_delete_validates_emptiness_and_preserves_record(self):
        factory = inlineformset_factory(
            Location, Location, formset=LocationInlineFormSet,
            fields=("name", "short_name", "type", "is_deleted"), extra=0, can_delete=True,
        )
        data = {
            "children-TOTAL_FORMS": "1", "children-INITIAL_FORMS": "1",
            "children-0-id": self.live.pk, "children-0-parent_location": self.parent.pk,
            "children-0-name": self.live.name, "children-0-short_name": self.live.short_name,
            "children-0-type": self.kind.pk, "children-0-DELETE": "on",
        }
        stock = ItemLocation.objects.create(item=self.item, location=self.live, amount=1)
        formset = factory(data, instance=self.parent, queryset=Location.active.all())
        self.assertFalse(formset.is_valid())
        self.assertIn("not empty", str(formset.non_form_errors()))
        stock.delete()
        formset = factory(data, instance=self.parent, queryset=Location.active.all())
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertTrue(Location.objects.get(pk=self.live.pk).is_deleted)
