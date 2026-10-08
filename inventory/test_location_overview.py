from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.html import parse_html
from django.urls import reverse
from PIL import Image

from .models import Item, ItemLocation, Location, LocationHistory, LocationType, MeasurementUnit


def html_elements(element):
    yield element
    for child in element.children:
        if not isinstance(child, str):
            yield from html_elements(child)


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class LocationOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        kind = LocationType.objects.create(name="Room", unique=True)
        cls.location = Location.objects.create(
            type=kind, name="Workshop", short_name="WORK",
            summary="Tools",
            physical_description="Wooden shelves beside the west entrance",
        )
        cls.user = get_user_model().objects.create_user(username="overview-editor")
        cls.group = Group.objects.create(name="Overview editors")
        cls.group.permissions.add(Permission.objects.get(
            content_type__app_label="inventory", codename="change_location",
        ))
        cls.user.groups.add(cls.group)
        cls.history_viewer = get_user_model().objects.create_user(username="history-viewer")
        cls.history_viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="inventory", codename="view_locationhistory",
        ))

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media_root = Path(directory.name)
        media_settings = override_settings(MEDIA_ROOT=directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.client.force_login(self.user)
        self.url = reverse("location_overview_update", args=[self.location.pk])
        self.history_url = reverse("location_history", args=[self.location.pk])

    @staticmethod
    def photo(name="overview.png", color="blue"):
        content = BytesIO()
        Image.new("RGB", (160, 120), color).save(content, format="PNG")
        return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")

    def data(self, **changes):
        return {
            "summary": self.location.summary,
            **changes,
        }

    def events(self):
        return LocationHistory.objects.filter(location=self.location).order_by("created_at", "pk")

    def history_client(self):
        client = Client()
        client.force_login(self.history_viewer)
        return client

    def test_group_permission_allows_saving_both_fields_and_records_author(self):
        response = self.client.post(self.url, self.data(
            summary="Hand tools", overview_photo=self.photo(),
        ))
        self.assertRedirects(response, self.location.get_absolute_url())
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Hand tools")
        self.assertTrue(self.location.overview_photo.storage.exists(self.location.overview_photo.name))
        event = self.events().get()
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertTrue(event.actor_name)
        self.assertEqual(event.event_type, "overview_updated")
        self.assertEqual(event.before, {"summary": "Tools", "overview_photo": ""})
        self.assertEqual(event.after, {
            "summary": self.location.summary,
            "overview_photo": self.location.overview_photo.name,
        })

    def test_photo_replacement_and_removal_keep_original_files_in_history(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        first_name = self.location.overview_photo.name
        self.client.post(self.url, self.data(overview_photo=self.photo(color="red")))
        self.location.refresh_from_db()
        second_name = self.location.overview_photo.name
        self.assertNotEqual(first_name, second_name)
        replacement = self.events().last()
        self.assertEqual(replacement.before["overview_photo"], first_name)
        self.assertEqual(replacement.after["overview_photo"], second_name)
        response = self.client.post(self.url, self.data(remove_photo="on"))
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        self.assertFalse(self.location.overview_photo)
        removal = self.events().last()
        self.assertEqual(removal.before["overview_photo"], second_name)
        self.assertEqual(removal.after["overview_photo"], "")
        storage = self.location.overview_photo.storage
        self.assertTrue(storage.exists(first_name))
        self.assertTrue(storage.exists(second_name))
        self.assertEqual(self.events().count(), 3)

    def test_summary_edit_preserves_photo_and_unrelated_location_fields(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        previous_photo = self.location.overview_photo.name
        response = self.client.post(self.url, self.data(
            summary="Updated", name="Forged name", short_name="FORGED", is_deleted="on",
            physical_description="Must not overwrite physical characteristics",
        ), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Updated")
        self.assertEqual(self.location.overview_photo.name, previous_photo)
        self.assertEqual(self.location.name, "Workshop")
        self.assertEqual(self.location.short_name, "WORK")
        self.assertFalse(self.location.is_deleted)
        self.assertEqual(self.location.physical_description, "Wooden shelves beside the west entrance")

    def test_no_op_save_does_not_add_history(self):
        response = self.client.post(self.url, self.data(), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["url"], self.location.get_absolute_url())
        self.assertFalse(self.events().exists())

    def test_invalid_summary_saves_nothing_and_reports_field_errors(self):
        for value in ("x" * 51, "First\nSecond", "First\rSecond"):
            with self.subTest(value=value):
                response = self.client.post(self.url, self.data(
                    summary=value, overview_photo=self.photo(),
                ), HTTP_ACCEPT="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("summary", response.json()["errors"])
                self.location.refresh_from_db()
                self.assertEqual(self.location.summary, "Tools")
                self.assertFalse(self.location.overview_photo)
                self.assertFalse(self.events().exists())
        self.assertFalse(any(path.is_file() for path in self.media_root.rglob("*")))

    def test_invalid_image_does_not_save_other_fields(self):
        response = self.client.post(self.url, self.data(
            summary="Must not be saved",
            overview_photo=SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"),
        ), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("overview_photo", response.json()["errors"])
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertFalse(self.location.overview_photo)
        self.assertFalse(self.events().exists())

    def test_invalid_non_ajax_submission_preserves_input_on_the_detail_page(self):
        pending_summary = "x" * 51
        response = self.client.post(self.url, self.data(summary=pending_summary))
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "inventory/location_detail.html")
        self.assertTrue(response.context["overview_editor_open"])
        form = response.context["overview_form"]
        self.assertEqual(form["summary"].value(), pending_summary)
        self.assertIn("summary", form.errors)
        self.assertEqual(response.context["object"].summary, "Tools")
        self.assertContains(response, self.location.physical_description, status_code=400)
        self.assertContains(response, pending_summary, status_code=400)
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertFalse(self.events().exists())

    def test_simultaneous_photo_removal_and_replacement_saves_neither(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        original_photo = self.location.overview_photo.name
        response = self.client.post(self.url, self.data(
            summary="Not saved", overview_photo=self.photo(color="red"), remove_photo="on",
        ), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("overview_photo", response.json()["errors"])
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertEqual(self.location.overview_photo.name, original_photo)
        self.assertEqual(self.events().count(), 1)
        self.assertEqual(len([path for path in self.media_root.rglob("*") if path.is_file()]), 1)

    def test_history_database_failure_rolls_back_all_location_fields(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        original_photo = self.location.overview_photo.name
        with patch.object(LocationHistory, "save", side_effect=IntegrityError("History unavailable")):
            with self.assertRaisesMessage(IntegrityError, "History unavailable"):
                self.client.post(self.url, self.data(
                    summary="Must roll back", overview_photo=self.photo(color="red"),
                ))
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertEqual(self.location.overview_photo.name, original_photo)
        self.assertTrue(self.location.overview_photo.storage.exists(original_photo))
        self.assertEqual(self.events().count(), 1)

    def test_summary_allows_fifty_characters(self):
        response = self.client.post(self.url, self.data(summary="x" * 50))
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "x" * 50)

    def test_anonymous_or_unpermitted_users_cannot_update_even_with_local_session(self):
        self.client.logout()
        response = self.client.post(self.url, self.data(summary="Anonymous edit"))
        self.assertIn(response.status_code, (302, 403))
        reader = get_user_model().objects.create_user(username="reader")
        self.client.force_login(reader)
        session = self.client.session
        session["is_zam_local"] = True
        session.save()
        self.assertEqual(self.client.post(self.url, self.data(summary="Unpermitted edit")).status_code, 403)
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertFalse(self.events().exists())

    def test_updates_require_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data(summary="No CSRF")).status_code, 403)
        self.location.refresh_from_db()
        self.assertEqual(self.location.summary, "Tools")
        self.assertFalse(self.events().exists())

    def test_detail_remains_public_but_editor_requires_permission(self):
        self.client.post(self.url, self.data(summary="Visible to everyone"))
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, self.url)
        self.client.logout()
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, "Visible to everyone")
        self.assertContains(detail, self.location.physical_description)
        self.assertNotContains(detail, self.history_url)
        self.assertNotContains(detail, self.url)

    def test_history_requires_view_permission_because_it_names_actors(self):
        self.client.post(self.url, self.data(summary="Recorded change"))
        actor_name = self.events().get().actor_name
        # The editor may change summaries, but seeing who changed them is separate.
        self.assertEqual(self.client.get(self.history_url).status_code, 403)
        self.client.logout()
        anonymous = self.client.get(self.history_url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertNotContains(anonymous, actor_name, status_code=302)
        reader = get_user_model().objects.create_user(username="reader")
        self.client.force_login(reader)
        session = self.client.session
        session["is_zam_local"] = True
        session.save()
        self.assertEqual(self.client.get(self.history_url).status_code, 403)
        history = self.history_client().get(self.history_url)
        self.assertContains(history, "Recorded change")
        self.assertContains(history, "Tools")
        self.assertContains(history, actor_name)

    def test_item_list_remains_expanded_and_keeps_every_item(self):
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        items = []
        for index in range(11):
            item = Item.objects.create(name=f"Stored item {index:02d}", measurement_unit=unit)
            ItemLocation.objects.create(item=item, location=self.location, amount=index + 1)
            items.append(item)
            if len(items) not in (10, 11):
                continue
            with self.subTest(count=len(items)):
                response = self.client.get(self.location.get_absolute_url())
                wrappers = [
                    element for element in html_elements(parse_html(response.content.decode()))
                    if dict(element.attributes).get("id") == "location-items-list"
                ]
                self.assertEqual(wrappers, [])
                visible_contents = response.content.decode()
                for stored in items:
                    self.assertIn(stored.name, visible_contents)
                    self.assertIn(stored.get_absolute_url(), visible_contents)

    def test_sublocation_list_remains_expanded_and_keeps_every_child(self):
        children = []
        for index in range(11):
            child = Location.objects.create(
                type=self.location.type, parent_location=self.location,
                name=f"Child location {index:02d}", short_name=f"CHILD{index}",
            )
            children.append(child)
            if len(children) not in (10, 11):
                continue
            with self.subTest(count=len(children)):
                response = self.client.get(self.location.get_absolute_url())
                wrappers = [
                    element for element in html_elements(parse_html(response.content.decode()))
                    if dict(element.attributes).get("id") == "location-children-list"
                ]
                self.assertEqual(wrappers, [])
                visible_contents = response.content.decode()
                for stored in children:
                    self.assertIn(stored.name, visible_contents)
                    self.assertIn(stored.get_absolute_url(), visible_contents)

    def test_overview_precedes_items_and_shows_summary_before_photo(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Stored drill", measurement_unit=unit)
        ItemLocation.objects.create(item=item, location=self.location, amount=1)
        self.client.logout()
        response = self.client.get(self.location.get_absolute_url())
        panel = next(
            element for element in html_elements(parse_html(response.content.decode()))
            if dict(element.attributes).get("aria-labelledby") == "location-stored-heading"
        )
        contents = str(panel)
        self.assertIn("Stored here", contents)
        self.assertLess(contents.index(self.location.summary), contents.index(self.location.overview_photo.url))
        self.assertLess(contents.index(self.location.overview_photo.url), contents.index('id="location-items-heading"'))
        self.assertIn(item.name, contents)

    def test_public_metadata_modal_opens_beside_the_physical_description(self):
        self.client.logout()
        label_url = "https://example.com/location-label.png"
        with patch.object(Location, "get_lablary_url", new=lambda location: label_url):
            response = self.client.get(self.location.get_absolute_url())
        elements = list(html_elements(parse_html(response.content.decode())))
        metadata = next(element for element in elements if dict(element.attributes).get("id") == "location-metadata")
        self.assertIn("modal", dict(metadata.attributes).get("class", "").split())
        self.assertEqual(dict(metadata.attributes).get("aria-hidden"), "true")
        self.assertIn(self.location.physical_description, str(metadata))
        self.assertIn(label_url, str(metadata))
        description = next(element for element in elements if "location-header-description" in dict(element.attributes).get("class", "").split())
        self.assertIn(self.location.physical_description, str(description))
        trigger = next(element for element in html_elements(description) if dict(element.attributes).get("data-bs-target") == "#location-metadata")
        self.assertEqual(trigger.name, "button")
        self.assertEqual(dict(trigger.attributes).get("data-bs-toggle"), "modal")
        self.assertIn("Location details", str(trigger))
        path = next(element for element in elements if "location-path" in dict(element.attributes).get("class", "").split())
        self.assertNotIn(path, list(html_elements(metadata)))
        self.assertIn(self.location.descriptive_identifier, str(path))

    def test_sublocation_panel_is_hidden_when_the_type_forbids_sublocations(self):
        self.client.logout()
        leaf = LocationType.objects.create(name="Box", unique=True, no_sublocations=True)
        box = Location.objects.create(type=leaf, name="Parts box", short_name="BOX")
        response = self.client.get(box.get_absolute_url())
        self.assertNotContains(response, 'id="location-children-heading"')
        self.assertContains(response, "location-layout-single")
        response = self.client.get(self.location.get_absolute_url())
        self.assertContains(response, 'id="location-children-heading"')
        self.assertNotContains(response, "location-layout-single")
        # Sub-locations from before the type changed must stay reachable.
        child = Location.objects.create(type=self.location.type, parent_location=box, name="Old child", short_name="OLD")
        response = self.client.get(box.get_absolute_url())
        self.assertContains(response, 'id="location-children-heading"')
        self.assertContains(response, child.get_absolute_url())
        self.assertNotContains(response, "location-layout-single")

    def test_metadata_modal_explains_the_current_location_type(self):
        self.client.logout()
        parent = Location.objects.create(type=self.location.type, name="Parent", short_name="PARENT")
        for unique, moveable, no_sublocations in ((True, True, False), (False, False, True)):
            with self.subTest(unique=unique, moveable=moveable, no_sublocations=no_sublocations):
                kind = LocationType.objects.create(
                    name=f"Type {unique}", unique=unique, moveable=moveable,
                    no_sublocations=no_sublocations,
                )
                self.location.type = kind
                self.location.parent_location = parent
                self.location.save()
                response = self.client.get(self.location.get_absolute_url())
                metadata = next(
                    element for element in html_elements(parse_html(response.content.decode()))
                    if dict(element.attributes).get("id") == "location-metadata"
                )
                contents = str(metadata)
                for value, true_text, false_text in (
                    (moveable, "Moving is allowed for this location type.", "Moving is disabled for this location type."),
                    (no_sublocations, "This location cannot contain sub-locations.", "This location can contain sub-locations."),
                    (unique, "The unique identifier is independent of the parent location.", "The unique identifier includes the parent location’s identifier."),
                ):
                    self.assertIn(true_text if value else false_text, contents)
                    self.assertNotIn(false_text if value else true_text, contents)

    def test_summary_html_is_escaped(self):
        self.client.post(self.url, self.data(summary='<img src=x onerror="alert(1)">'))
        self.client.logout()
        for url, client in ((self.location.get_absolute_url(), self.client), (self.history_url, self.history_client())):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
                self.assertNotContains(response, '<img src=x onerror="alert(1)">')

    def test_history_keeps_actor_snapshot_after_account_is_deleted(self):
        self.client.post(self.url, self.data(summary="Recorded change"))
        event = self.events().get()
        actor_name = event.actor_name
        self.client.logout()
        self.user.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_name, actor_name)
        self.assertContains(self.history_client().get(self.history_url), actor_name)

    def test_history_is_paginated_and_newest_first(self):
        events = LocationHistory.objects.bulk_create([
            LocationHistory(
                location=self.location, actor=self.user, actor_name=self.user.username,
                before={"summary": "Previous"}, after={"summary": f"Change {index}"},
            )
            for index in range(26)
        ])
        client = self.history_client()
        first_page = client.get(self.history_url)
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.context["paginator"].num_pages, 2)
        self.assertEqual([event.pk for event in first_page.context["page_obj"]], [event.pk for event in reversed(events[1:])])
        self.assertContains(first_page, "?page=2")
        second_page = client.get(self.history_url, {"page": 2})
        self.assertEqual(list(second_page.context["page_obj"]), [events[0]])
        self.assertContains(second_page, "Change 0")
        self.assertEqual(client.get(self.history_url, {"page": 3}).status_code, 404)

    def test_admin_changes_record_parent_and_inline_overview_history(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        child = Location.objects.create(
            type=self.location.type, name="Child", short_name="CHILD",
            parent_location=self.location, summary="Original child",
        )
        response = self.client.post(reverse("admin:inventory_location_change", args=[self.location.pk]), {
            "id": self.location.pk, "name": self.location.name, "short_name": self.location.short_name,
            "type": self.location.type_id, "summary": "Admin overview",
            "physical_description": self.location.physical_description,
            "children-TOTAL_FORMS": "1", "children-INITIAL_FORMS": "1",
            "children-MIN_NUM_FORMS": "0", "children-MAX_NUM_FORMS": "1000",
            "children-0-id": child.pk, "children-0-parent_location": self.location.pk,
            "children-0-type": child.type_id, "children-0-name": child.name,
            "children-0-short_name": child.short_name, "children-0-summary": "Updated child",
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(self.location.summary, "Admin overview")
        self.assertEqual(child.summary, "Updated child")
        parent_event = self.events().get()
        child_event = LocationHistory.objects.get(location=child)
        self.assertEqual(parent_event.before["summary"], "Tools")
        self.assertEqual(parent_event.after["summary"], "Admin overview")
        self.assertEqual(child_event.before["summary"], "Original child")
        self.assertEqual(child_event.after["summary"], "Updated child")
        self.assertEqual(parent_event.actor_id, self.user.pk)
        self.assertEqual(child_event.actor_id, self.user.pk)

    def test_deleted_locations_cannot_be_viewed_or_updated(self):
        Location.objects.filter(pk=self.location.pk).update(is_deleted=True)
        self.assertEqual(self.client.get(self.location.get_absolute_url()).status_code, 404)
        self.assertEqual(self.history_client().get(self.history_url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.data(summary="Archived edit")).status_code, 404)
        self.assertFalse(self.events().exists())

    def test_location_search_and_autocompletes_match_summary_and_physical_description(self):
        Location.objects.filter(pk=self.location.pk).update(summary="Electric tools")
        Location.objects.create(
            type=self.location.type, name="Unrelated", short_name="OTHER", summary="No match",
        )
        deleted = Location.objects.create(
            type=self.location.type, name="Deleted", short_name="DELETED",
            summary="Electric tools", physical_description="West wall", is_deleted=True,
        )
        self.client.logout()
        for query in ("eLeCtRiC", "wEsT"):
            with self.subTest(query=query):
                response = self.client.get(reverse("index_locations"), {"q": query})
                self.assertEqual(list(response.context["object_list"]), [self.location])
                for name in ("location-autocomplete", "parent_location_autocomplete"):
                    with self.subTest(autocomplete=name):
                        response = self.client.get(reverse(name), {"q": query})
                        self.assertEqual(response.status_code, 200)
                        ids = {str(result["id"]) for result in response.json()["results"]}
                        self.assertEqual(ids, {str(self.location.pk)})
                        self.assertNotIn(str(deleted.pk), ids)


class LocationOverviewMigrationTests(TransactionTestCase):
    def test_existing_description_becomes_physical_description_without_inventing_history(self):
        before = [("inventory", "0017_alter_item_options")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            kind = apps.get_model("inventory", "LocationType").objects.create(name="Room", unique=True)
            LocationBefore = apps.get_model("inventory", "Location")
            saved = LocationBefore.objects.create(
                type=kind, name="Old location", short_name="OLD", unique_identifier="OLD",
                locatable_identifier="OLD", descriptive_identifier="Old location",
                description="A blue steel cabinet, 2 m high",
            )
            saved_pk = saved.pk
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            location = apps.get_model("inventory", "Location").objects.get(pk=saved_pk)
            self.assertEqual(location.physical_description, "A blue steel cabinet, 2 m high")
            self.assertFalse(hasattr(location, "description"))
            self.assertEqual(location.summary, "")
            self.assertFalse(location.overview_photo)
            self.assertFalse(apps.get_model("inventory", "LocationHistory").objects.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
