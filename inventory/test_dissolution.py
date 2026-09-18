from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Item, ItemLocation, Location, LocationType, MeasurementUnit


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class DissolveLocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.room_type = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.box_type = LocationType.objects.create(name="Box", moveable=True)
        cls.parent = Location.objects.create(type=cls.room_type, name="Parent", short_name="P")
        cls.root = Location.objects.create(type=cls.box_type, name="Root", short_name="R", parent_location=cls.parent)
        cls.child = Location.objects.create(type=cls.box_type, name="Child", short_name="C", parent_location=cls.root)
        cls.leaf = Location.objects.create(type=cls.box_type, name="Leaf", short_name="L", parent_location=cls.child)
        cls.destination = Location.objects.create(type=cls.room_type, name="Destination", short_name="D")
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        cls.item = Item.objects.create(name="Main item", measurement_unit=unit)
        cls.nested_item = Item.objects.create(name="Nested item", measurement_unit=unit)
        cls.stock = ItemLocation.objects.create(item=cls.item, location=cls.root, amount=-25)
        cls.nested_stock = ItemLocation.objects.create(item=cls.nested_item, location=cls.leaf, amount=-9999)
        cls.user = get_user_model().objects.create_user(username="dissolver")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("location_dissolve", kwargs={"pk": self.root.pk})

    def data(self, recursive=False, action="move"):
        objects = [("item", self.stock), ("location", self.child)]
        if recursive:
            objects += [("item", self.nested_stock), ("location", self.leaf)]
        values = {"recursive": "1" if recursive else "0", "stage": "review"}
        for kind, obj in objects:
            values[f"{kind}_{obj.pk}_delete"] = action == "delete"
            if action == "move":
                values[f"{kind}_{obj.pk}_destination"] = str(self.destination.pk)
        return values

    def confirm(self, response, **extra):
        return self.client.post(self.url, {"stage": "confirm", "plan": response.context["plan_token"], **extra})

    def assert_unchanged(self):
        self.assertTrue(Location.objects.filter(pk=self.root.pk).exists())
        self.child.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(self.child.parent_location_id, self.root.pk)
        self.assertEqual(self.stock.location_id, self.root.pk)

    def test_action_and_scope_default_and_recursive(self):
        detail = self.client.get(self.root.get_absolute_url())
        self.assertContains(detail, f'href="{self.url}"')
        response = self.client.get(self.url)
        self.assertContains(response, "Main item")
        self.assertNotContains(response, "Nested item")
        self.assertEqual(len(response.context["form"].rows), 2)
        recursive = self.client.get(self.url, {"recursive": "1"})
        self.assertContains(recursive, "Nested item")
        self.assertEqual(len(recursive.context["form"].rows), 4)
        self.assert_unchanged()

    def test_review_and_edit_never_move_or_delete(self):
        response = self.client.post(self.url, self.data())
        self.assertTemplateUsed(response, "inventory/location_dissolve_confirm.html")
        self.assertContains(response, "To be moved")
        self.assertContains(response, "To be deleted")
        self.assertContains(response, "Root")
        self.assert_unchanged()
        edit = self.client.post(self.url, {"stage": "edit", "plan": response.context["plan_token"]})
        self.assertEqual(str(edit.context["form"][f"item_{self.stock.pk}_destination"].value()), str(self.destination.pk))
        self.assert_unchanged()

    def test_confirmation_moves_contents_then_deletes_empty_root(self):
        response = self.confirm(self.client.post(self.url, self.data()))
        self.assertRedirects(response, self.parent.get_absolute_url())
        self.assertFalse(Location.objects.filter(pk=self.root.pk).exists())
        self.stock.refresh_from_db()
        self.child.refresh_from_db()
        self.leaf.refresh_from_db()
        self.nested_stock.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.destination.pk)
        self.assertEqual(self.stock.amount, -25)
        self.assertEqual(self.child.parent_location_id, self.destination.pk)
        self.assertEqual(self.leaf.unique_identifier, "D.C.L")
        self.assertEqual(self.nested_stock.location_id, self.leaf.pk)
        self.assertTrue(Item.objects.filter(pk=self.item.pk).exists())

    def test_recursive_delete_all_preserves_items(self):
        response = self.client.post(self.url, self.data(recursive=True, action="delete"))
        self.assertEqual(len(response.context["deletions"]), 4)
        self.assertContains(response, "Nested item")
        self.assert_unchanged()
        self.confirm(response)
        self.assertFalse(Location.objects.filter(pk__in=[self.root.pk, self.child.pk, self.leaf.pk]).exists())
        self.assertFalse(ItemLocation.objects.filter(pk__in=[self.stock.pk, self.nested_stock.pk]).exists())
        self.assertEqual(Item.objects.filter(pk__in=[self.item.pk, self.nested_item.pk]).count(), 2)

    def test_delete_nonempty_child_is_rejected_without_recursion(self):
        response = self.client.post(self.url, self.data(action="delete"))
        self.assertNotIn("plan_token", response.context)
        self.assertContains(response, "still has sub-locations")
        self.assert_unchanged()

    def test_delete_checkbox_ignores_destination_and_survives_editing(self):
        data = self.data(recursive=True, action="delete")
        data[f"item_{self.stock.pk}_destination"] = "missing-location"
        review = self.client.post(self.url, data)
        self.assertTemplateUsed(review, "inventory/location_dissolve_confirm.html")
        edit = self.client.post(self.url, {"stage": "edit", "plan": review.context["plan_token"]})
        form = edit.context["form"]
        self.assertTrue(form[f"item_{self.stock.pk}_delete"].value())
        self.assertTrue(form.fields[f"item_{self.stock.pk}_destination"].disabled)
        self.assert_unchanged()
        # Unchecking returns the row to a move and requires a valid destination.
        data[f"item_{self.stock.pk}_delete"] = False
        data[f"item_{self.stock.pk}_destination"] = ""
        response = self.client.post(self.url, data)
        self.assertContains(response, "Choose a destination.")
        self.assertFalse(response.context["form"].fields[f"item_{self.stock.pk}_destination"].disabled)
        self.assert_unchanged()

    def test_recursive_move_descendants_and_delete_their_emptied_parent(self):
        data = self.data(recursive=True)
        data[f"location_{self.child.pk}_delete"] = True
        response = self.client.post(self.url, data)
        self.confirm(response)
        self.assertFalse(Location.objects.filter(pk=self.child.pk).exists())
        self.leaf.refresh_from_db()
        self.nested_stock.refresh_from_db()
        self.assertEqual(self.leaf.parent_location_id, self.destination.pk)
        self.assertEqual(self.nested_stock.location_id, self.destination.pk)

    def test_items_can_move_into_a_sublocation_that_also_moves(self):
        data = self.data()
        data[f"item_{self.stock.pk}_destination"] = str(self.child.pk)
        self.confirm(self.client.post(self.url, data))
        self.stock.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.child.pk)
        self.assertEqual(self.child.parent_location_id, self.destination.pk)

    def test_missing_destinations_and_deleted_destinations_are_rejected(self):
        data = self.data()
        del data[f"item_{self.stock.pk}_destination"]
        response = self.client.post(self.url, data)
        self.assertContains(response, "Choose a destination.")
        data = self.data(recursive=True, action="delete")
        data[f"item_{self.stock.pk}_delete"] = False
        data[f"item_{self.stock.pk}_destination"] = str(self.child.pk)
        self.assertContains(self.client.post(self.url, data), "still contains items")
        self.assert_unchanged()

    def test_cycles_are_rejected(self):
        data = self.data()
        data[f"location_{self.child.pk}_destination"] = str(self.leaf.pk)
        response = self.client.post(self.url, data)
        self.assertContains(response, "may not contain cycles")
        self.assert_unchanged()

    def test_duplicate_stock_destinations_are_not_merged(self):
        ItemLocation.objects.create(item=self.item, location=self.destination, amount=8)
        response = self.client.post(self.url, self.data())
        self.assertContains(response, "quantities are not merged automatically")
        self.assert_unchanged()

    def test_immovable_locations_and_invalid_destination_types(self):
        self.box_type.moveable = False
        self.box_type.save()
        self.assertContains(self.client.post(self.url, self.data()), "Moving is disabled")
        self.box_type.moveable = True
        self.box_type.save()
        self.room_type.no_sublocations = True
        self.room_type.save()
        response = self.client.post(self.url, self.data())
        self.assertNotIn("plan_token", response.context)
        self.assert_unchanged()

    def test_signed_confirmation_required_and_cannot_be_changed(self):
        token = self.client.post(self.url, self.data()).context["plan_token"]
        for invalid in ("", token + "tampered"):
            response = self.client.post(self.url, {"stage": "confirm", "plan": invalid})
            self.assertRedirects(response, self.url)
            self.assert_unchanged()
        other_url = reverse("location_dissolve", kwargs={"pk": self.destination.pk})
        self.client.post(other_url, {"stage": "confirm", "plan": token})
        self.assertTrue(Location.objects.filter(pk=self.destination.pk).exists())
        self.assert_unchanged()

    def test_confirmation_expires(self):
        response = self.client.post(self.url, self.data())
        with patch("django.core.signing.time.time", return_value=99999999999):
            self.assertEqual(self.confirm(response).status_code, 302)
        self.assert_unchanged()

    def test_changed_quantity_or_new_child_invalidates_confirmation(self):
        response = self.client.post(self.url, self.data())
        self.stock.amount = 42
        self.stock.save()
        result = self.confirm(response)
        self.assertContains(result, "The inventory changed")
        self.assert_unchanged()
        response = self.client.post(self.url, self.data())
        Location.objects.create(type=self.box_type, name="New child", short_name="NEW", parent_location=self.root)
        self.assertContains(self.confirm(response), "The inventory changed")
        self.assert_unchanged()

    def test_failure_rolls_back_moves_and_deletions(self):
        data = self.data(recursive=True)
        data[f"item_{self.stock.pk}_delete"] = True
        response = self.client.post(self.url, data)
        original = Location.delete

        def fail_at_root(location, *args, **kwargs):
            if location.pk == self.root.pk:
                raise ValidationError("Cannot delete now")
            return original(location, *args, **kwargs)

        with patch.object(Location, "delete", fail_at_root):
            result = self.confirm(response)
        self.assertContains(result, "Cannot delete now")
        self.assert_unchanged()
        self.nested_stock.refresh_from_db()
        self.assertEqual(self.nested_stock.location_id, self.leaf.pk)

    def test_empty_location_still_requires_confirmation(self):
        self.url = reverse("location_dissolve", kwargs={"pk": self.destination.pk})
        self.assertContains(self.client.get(self.url), "already empty")
        response = self.client.post(self.url, {"stage": "review"})
        self.assertTrue(Location.objects.filter(pk=self.destination.pk).exists())
        self.assertRedirects(self.confirm(response), reverse("index_locations"))
        self.assertFalse(Location.objects.filter(pk=self.destination.pk).exists())

    def test_authentication_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data()).status_code, 403)
        self.assert_unchanged()
