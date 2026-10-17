from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..models import Item, ItemLocation, Location, LocationType, MeasurementUnit, UniqueItem


TEST_SETTINGS = override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)


class DissolutionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Deletable without admin access, so the plans here are not limited by the location type.
        cls.room_type = LocationType.objects.create(name="Room", unique=True, moveable=True, deletable_in_frontend=True)
        cls.box_type = LocationType.objects.create(name="Box", moveable=True, deletable_in_frontend=True)
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
        cls.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory",
            codename__in=["delete_location", "change_location", "change_itemlocation", "delete_itemlocation"],
        ))

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("location_dissolve", kwargs={"pk": self.root.pk})

    def assert_unchanged(self):
        self.assertTrue(Location.active.filter(pk=self.root.pk).exists())
        self.child.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(self.child.parent_location_id, self.root.pk)
        self.assertEqual(self.stock.location_id, self.root.pk)


@TEST_SETTINGS
class DissolveLocationTests(DissolutionTestCase):
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
        self.assertFalse(Location.active.filter(pk=self.root.pk).exists())
        self.assertTrue(Location.objects.get(pk=self.root.pk).is_deleted)
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
        self.assertFalse(Location.active.filter(pk__in=[self.root.pk, self.child.pk, self.leaf.pk]).exists())
        self.assertEqual(Location.objects.filter(pk__in=[self.root.pk, self.child.pk, self.leaf.pk], is_deleted=True).count(), 3)
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
        self.assertFalse(Location.active.filter(pk=self.child.pk).exists())
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
        self.assertContains(self.client.post(self.url, data), "This destination is deleted by the plan.")
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
        self.assertFalse(Location.active.filter(pk=self.destination.pk).exists())

    def test_authentication_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data()).status_code, 403)
        self.assert_unchanged()


@TEST_SETTINGS
class MoveContentsTests(DissolutionTestCase):
    """The same plan without deleting the location: partial or complete mass-moves."""

    def post(self, rows, recursive=False, delete="0"):
        data = {"recursive": "1" if recursive else "0", "delete": delete, "stage": "review"}
        for (kind, obj), value in rows.items():
            if value == "delete":
                data[f"{kind}_{obj.pk}_delete"] = "on"
            elif value is not None:
                data[f"{kind}_{obj.pk}_destination"] = str(value.pk)
        return self.client.post(self.url, data)

    def confirm(self, response):
        return self.client.post(self.url, {"stage": "confirm", "plan": response.context["plan_token"]})

    def test_detail_page_offers_moving_contents(self):
        detail = self.client.get(self.root.get_absolute_url())
        self.assertContains(detail, f'href="{self.url}?delete=0"')
        response = self.client.get(self.url, {"delete": "0"})
        self.assertContains(response, "Move contents")
        self.assertFalse(response.context["delete_root"])
        self.assertTrue(self.client.get(self.url).context["delete_root"])

    def test_partial_move_keeps_location_and_unselected_entries(self):
        review = self.post({("item", self.stock): self.destination})
        self.assertTemplateUsed(review, "inventory/location_dissolve_confirm.html")
        self.assertContains(review, "1 entry stays where it is.")
        self.assertNotContains(review, "Deleted last")
        response = self.confirm(review)
        self.assertRedirects(response, self.root.get_absolute_url())
        self.assertTrue(Location.active.filter(pk=self.root.pk).exists())
        self.stock.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.destination.pk)
        self.assertEqual(self.child.parent_location_id, self.root.pk)

    def test_complete_move_leaves_an_empty_location(self):
        self.confirm(self.post({("item", self.stock): self.destination, ("location", self.child): self.destination}))
        root = Location.active.get(pk=self.root.pk)
        self.assertFalse(root.children.filter(is_deleted=False).exists())
        self.assertFalse(root.itemlocation_set.exists())

    def test_sub_locations_can_be_emptied_and_kept_or_deleted(self):
        rows = {
            ("item", self.stock): None, ("location", self.child): None,
            ("item", self.nested_stock): self.root, ("location", self.leaf): "delete",
        }
        self.confirm(self.post(rows, recursive=True))
        self.nested_stock.refresh_from_db()
        self.assertEqual(self.nested_stock.location_id, self.root.pk)
        self.assertTrue(Location.objects.get(pk=self.leaf.pk).is_deleted)
        self.assertEqual(Location.active.filter(pk__in=[self.root.pk, self.child.pk]).count(), 2)
        # Kept, emptied sub-location.
        rows[("location", self.leaf)] = None
        self.leaf.is_deleted = False
        self.leaf.save()
        ItemLocation.objects.filter(pk=self.nested_stock.pk).update(location=self.leaf)
        self.confirm(self.post(rows, recursive=True))
        self.assertTrue(Location.active.filter(pk=self.leaf.pk).exists())
        self.assertFalse(ItemLocation.objects.filter(location=self.leaf).exists())

    def test_root_is_a_destination_only_while_kept(self):
        rows = {("item", self.nested_stock): self.root}
        self.assertIn("plan_token", self.post(rows, recursive=True).context)
        response = self.post({**rows, ("item", self.stock): "delete", ("location", self.child): "delete",
                              ("location", self.leaf): "delete"}, recursive=True, delete="1")
        self.assertNotIn("plan_token", response.context)
        self.assert_unchanged()

    def test_kept_entries_in_a_deleted_location_are_reported_on_the_row(self):
        response = self.post({("item", self.stock): None, ("location", self.child): self.destination}, delete="1")
        self.assertNotIn("plan_token", response.context)
        self.assertEqual(response.context["form"].errors[f"item_{self.stock.pk}_destination"], ["Choose a destination."])
        response = self.post({("location", self.child): None, ("item", self.nested_stock): self.destination,
                              ("location", self.leaf): None, ("item", self.stock): None}, recursive=True)
        self.assertIn("plan_token", response.context)
        response = self.post({("location", self.child): "delete", ("location", self.leaf): None,
                              ("item", self.nested_stock): None, ("item", self.stock): None}, recursive=True)
        self.assertIn(f"location_{self.leaf.pk}_destination", response.context["form"].errors)

    def test_a_plan_that_changes_nothing_is_rejected(self):
        response = self.post({})
        self.assertNotIn("plan_token", response.context)
        self.assertContains(response, "Nothing to do")

    def test_empty_location_has_nothing_to_move(self):
        response = self.client.get(reverse("location_dissolve", kwargs={"pk": self.destination.pk}), {"delete": "0"})
        self.assertContains(response, "There is nothing to move.")
        # Nothing to keep in place: only deleting the empty location is offered.
        self.assertNotContains(response, "Review and keep location")
        self.assertContains(response, '<button class="btn btn-outline-danger" type="submit" name="delete" value="1">Review and delete location</button>', html=True)

    def test_unique_items_stay_in_a_kept_location(self):
        unique_item = UniqueItem.objects.create(item=self.item, location=self.root)
        response = self.client.get(self.url, {"delete": "0"})
        self.assertFalse(response.context["blocking_unique_items"])
        self.confirm(self.post({("item", self.stock): self.destination}))
        self.assertEqual(UniqueItem.objects.get(pk=unique_item.pk).location_id, self.root.pk)
        response = self.post({("location", self.child): self.destination}, delete="1")
        self.assertContains(response, "Unique items are still stored here.")

    def test_moving_contents_needs_no_delete_permission(self):
        mover = get_user_model().objects.create_user(username="mover")
        mover.user_permissions.add(Permission.objects.get(content_type__app_label="inventory", codename="change_itemlocation"))
        self.client.force_login(mover)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        response = self.client.get(self.url, {"delete": "0"})
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.fields[f"location_{self.child.pk}_destination"].disabled)
        self.assertContains(response, "You do not have permission to delete this location.")
        # Locations the user may not move stay in place.
        review = self.post({("item", self.stock): self.destination, ("location", self.child): self.destination})
        self.assertIn("plan_token", review.context)
        self.confirm(review)
        self.stock.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.stock.location_id, self.destination.pk)
        self.assertEqual(self.child.parent_location_id, self.root.pk)
        self.assertTrue(Location.active.filter(pk=self.root.pk).exists())
        # Asking to delete the location still requires the permission.
        self.assertEqual(self.post({("location", self.child): self.destination}, delete="1").status_code, 403)
        self.assertTrue(Location.active.filter(pk=self.root.pk).exists())


@TEST_SETTINGS
class LocationTypeDeletionTests(DissolutionTestCase):
    """Outside the admin, only locations of types that allow it can be deleted (LocationType.deletable_in_frontend)."""

    def setUp(self):
        super().setUp()
        LocationType.objects.filter(pk=self.box_type.pk).update(deletable_in_frontend=False)

    def review(self, **values):
        return self.client.post(self.url, {"recursive": "0", "stage": "review", **values})

    def test_protected_root_cannot_be_dissolved_but_its_contents_can_move(self):
        detail = self.client.get(self.root.get_absolute_url())
        self.assertNotContains(detail, f'href="{self.url}"')
        self.assertContains(detail, "Locations of type “Box” can only be deleted in the admin.")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        page = self.client.get(self.url, {"delete": "0"})
        self.assertContains(page, 'title="Locations of type “Box” can only be deleted in the admin."')
        self.assertNotContains(page, 'name="delete" value="1">')
        self.assertContains(page, 'name="delete" value="0">Review and keep location')
        self.assertEqual(self.review(delete="1").status_code, 403)
        self.assert_unchanged()

    def test_protected_sub_location_cannot_be_selected_or_forged_for_deletion(self):
        LocationType.objects.filter(pk=self.room_type.pk).update(deletable_in_frontend=True)
        Location.objects.filter(pk=self.root.pk).update(type=self.room_type)
        page = self.client.get(self.url)
        self.assertContains(page, "Locations of type “Box” can only be deleted in the admin.")
        response = self.review(**{f"location_{self.child.pk}_delete": "on", f"item_{self.stock.pk}_destination": self.destination.pk})
        self.assertNotIn("plan_token", response.context or {})
        self.assertTrue(Location.active.filter(pk=self.child.pk).exists())
        # A confirmation that claims to delete it anyway is refused.
        from django.core import signing
        from ..dissolve_views import DissolveLocationView
        from ..dissolution import DissolutionPlan
        plan = DissolutionPlan(self.root, delete_root=True)
        operations = [["item", self.stock.pk, "move", self.destination.pk], ["location", self.child.pk, "delete", None]]
        token = signing.dumps({"root": self.root.pk, "recursive": False, "delete_root": True, "operations": operations,
                               "fingerprint": plan.fingerprint()}, salt=DissolveLocationView.salt, compress=True)
        self.assertEqual(self.client.post(self.url, {"stage": "confirm", "plan": token}).status_code, 403)
        self.assertTrue(Location.active.filter(pk=self.child.pk).exists())

    def test_plan_ends_with_keep_or_delete_buttons(self):
        LocationType.objects.filter(pk=self.box_type.pk).update(deletable_in_frontend=True)
        for params, primary in (({}, "btn-danger"), ({"delete": "0"}, "btn-primary")):
            with self.subTest(params=params):
                page = self.client.get(self.url, params).content.decode()
                self.assertNotIn('id="delete-root"', page)
                keep = page.index('name="delete" value="0">Review and keep location')
                delete = page.index('name="delete" value="1">Review and delete location')
                self.assertLess(keep, delete)  # Enter in a field submits the first: keeping
                self.assertIn(primary, page[keep - 80:delete])
        # The button decides whether the location is deleted.
        response = self.client.post(self.url, {"recursive": "0", "stage": "review", "delete": "0",
                                               f"item_{self.stock.pk}_destination": self.destination.pk,
                                               f"location_{self.child.pk}_destination": self.destination.pk})
        self.assertFalse(response.context["delete_root"])

    def test_unique_items_disable_deleting_but_not_keeping(self):
        LocationType.objects.filter(pk=self.box_type.pk).update(deletable_in_frontend=True)
        UniqueItem.objects.create(item=self.item, location=self.root)
        page = self.client.get(self.url, {"delete": "0"})
        self.assertContains(page, 'title="Unique items are still stored here. Move them or remove them from the inventory first."')
        self.assertContains(page, 'name="delete" value="0">Review and keep location')

    def test_location_details_show_whether_non_admins_may_delete(self):
        self.assertContains(self.client.get(self.root.get_absolute_url()), "Locations of this type can only be deleted in the admin.")
        LocationType.objects.filter(pk=self.box_type.pk).update(deletable_in_frontend=True)
        self.assertContains(self.client.get(self.root.get_absolute_url()),
                            "Everyone with the delete permission may delete locations of this type here.")

    def test_staff_too_delete_protected_types_only_in_the_admin(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from ..admin import LocationAdmin
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=True)
        staff = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_login(staff)
        self.assertContains(self.client.get(self.root.get_absolute_url()), "can only be deleted in the admin")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        request = RequestFactory().get("/admin/")
        request.user = staff
        self.assertTrue(LocationAdmin(Location, admin.site).has_delete_permission(request, self.root))

    def test_without_the_delete_permission_the_type_does_not_matter(self):
        LocationType.objects.filter(pk=self.box_type.pk).update(deletable_in_frontend=True)
        self.user.user_permissions.remove(Permission.objects.get(codename="delete_location"))
        self.client.force_login(get_user_model().objects.get(pk=self.user.pk))
        self.assertContains(self.client.get(self.root.get_absolute_url()), "You do not have permission to delete this location.")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_migration_allows_the_agreed_types(self):
        from importlib import import_module
        from django.apps import apps
        migration = import_module("inventory.migrations.0034_location_type_deletable_in_frontend")
        names = ["Haus+Etage", "Raum/Bereich", "Kiste", "Regal", "Fach/Schub", "Karton", "Palette", "Schrank", "Other"]
        for name in names:
            LocationType.objects.create(name=name)
        migration.allow_deletion(apps, None)
        allowed = set(LocationType.objects.filter(name__in=names, deletable_in_frontend=True).values_list("name", flat=True))
        self.assertEqual(allowed, {"Regal", "Fach/Schub", "Karton", "Palette", "Schrank"})
