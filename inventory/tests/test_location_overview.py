import re
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

from ..models import ChangeLog, Item, ItemLocation, Location, LocationType, MeasurementUnit


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
        "inventory.actor.CurrentActorMiddleware",
    ],
    LANGUAGE_CODE="en",
)
class LocationOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        kind = LocationType.objects.create(name="Room", unique=True)
        cls.location = Location.objects.create(
            type=kind, name="Workshop", short_name="WORK",
            purpose="Tools",
            physical_description="Wooden shelves beside the west entrance",
        )
        cls.user = get_user_model().objects.create_user(username="overview-editor")
        cls.group = Group.objects.create(name="Overview editors")
        cls.group.permissions.add(Permission.objects.get(
            content_type__app_label="inventory", codename="change_location",
        ))
        cls.user.groups.add(cls.group)
        cls.history_viewer = get_user_model().objects.create_user(username="history-viewer")
        cls.history_viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="inventory", codename__in=["view_changelog", "view_changelog_actor"],
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
        self.purpose_url = reverse("location_purpose_update", args=[self.location.pk])

    @staticmethod
    def photo(name="overview.png", color="blue"):
        content = BytesIO()
        Image.new("RGB", (160, 120), color).save(content, format="PNG")
        return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")

    @staticmethod
    def data(**changes):
        """A submission of the overview photo editor."""
        return changes

    def post_purpose(self, purpose, client=None, **extra):
        return (client or self.client).post(self.purpose_url, {"purpose": purpose, **extra.pop("data", {})}, **extra)

    def events(self):
        """Changes of the location itself after it was created."""
        return ChangeLog.objects.filter(location=self.location, subject_type="location").exclude(
            action=ChangeLog.Action.CREATED).order_by("created_at", "pk")

    @staticmethod
    def changed(event, field):
        return next((change["before"], change["after"]) for change in event.changes if change["field"] == field)

    def history_client(self):
        client = Client()
        client.force_login(self.history_viewer)
        return client

    def test_purpose_and_photo_are_saved_separately_and_record_author(self):
        response = self.post_purpose("Hand tools")
        self.assertRedirects(response, self.location.get_absolute_url())
        response = self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.assertRedirects(response, self.location.get_absolute_url())
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Hand tools")
        self.assertTrue(self.location.overview_photo.storage.exists(self.location.overview_photo.name))
        purpose_event, photo_event = self.events()
        for event in (purpose_event, photo_event):
            self.assertEqual(event.actor_id, self.user.pk)
            self.assertTrue(event.actor_name)
            self.assertEqual(event.action, ChangeLog.Action.CHANGED)
            self.assertEqual(event.source, ChangeLog.Source.WEB)
        self.assertEqual(purpose_event.changes, [
            {"field": "purpose", "before": "Tools", "after": "Hand tools", "internal": False}])
        self.assertEqual([change["field"] for change in photo_event.changes], ["overview_photo"])
        self.assertEqual(self.changed(photo_event, "overview_photo"),
                         ("", Path(self.location.overview_photo.name).name))

    def test_photo_replacement_and_removal_keep_original_files_in_history(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        first_name = self.location.overview_photo.name
        self.client.post(self.url, self.data(overview_photo=self.photo(color="red")))
        self.location.refresh_from_db()
        second_name = self.location.overview_photo.name
        self.assertNotEqual(first_name, second_name)
        replacement = self.events().last()
        self.assertEqual(self.changed(replacement, "overview_photo"), (Path(first_name).name, Path(second_name).name))
        response = self.client.post(self.url, self.data(remove_photo="on"))
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        self.assertFalse(self.location.overview_photo)
        removal = self.events().last()
        self.assertEqual(self.changed(removal, "overview_photo"), (Path(second_name).name, ""))
        storage = self.location.overview_photo.storage
        self.assertTrue(storage.exists(first_name))
        self.assertTrue(storage.exists(second_name))
        self.assertEqual(self.events().count(), 3)

    def test_purpose_edit_preserves_photo_and_unrelated_location_fields(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        previous_photo = self.location.overview_photo.name
        response = self.post_purpose("Updated", data={
            "name": "Forged name", "short_name": "FORGED", "is_deleted": "on", "remove_photo": "on",
            "physical_description": "Must not overwrite physical characteristics",
        }, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Updated")
        self.assertEqual(self.location.overview_photo.name, previous_photo)
        self.assertEqual(self.location.name, "Workshop")
        self.assertEqual(self.location.short_name, "WORK")
        self.assertFalse(self.location.is_deleted)
        self.assertEqual(self.location.physical_description, "Wooden shelves beside the west entrance")
        # The photo editor in turn leaves the purpose alone.
        self.client.post(self.url, self.data(purpose="Forged purpose", overview_photo=self.photo(color="red")))
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Updated")

    def test_no_op_save_does_not_add_history(self):
        for response in (self.post_purpose("Tools", HTTP_ACCEPT="application/json"),
                         self.client.post(self.url, self.data(), HTTP_ACCEPT="application/json")):
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
            self.assertEqual(response.json()["url"], self.location.get_absolute_url())
        self.assertFalse(self.events().exists())

    def test_invalid_purpose_saves_nothing_and_reports_field_errors(self):
        for value in ("x" * 51, "First\nSecond", "First\rSecond"):
            with self.subTest(value=value):
                response = self.post_purpose(value, HTTP_ACCEPT="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("purpose", response.json()["errors"])
                self.location.refresh_from_db()
                self.assertEqual(self.location.purpose, "Tools")
                self.assertFalse(self.events().exists())

    def test_invalid_image_does_not_save_other_fields(self):
        response = self.client.post(self.url, self.data(
            overview_photo=SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"),
        ), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("overview_photo", response.json()["errors"])
        self.location.refresh_from_db()
        self.assertFalse(self.location.overview_photo)
        self.assertFalse(self.events().exists())

    def test_invalid_non_ajax_submission_preserves_input_on_the_detail_page(self):
        pending_purpose = "x" * 51
        response = self.post_purpose(pending_purpose)
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "inventory/location_detail.html")
        self.assertTrue(response.context["purpose_editor_open"])
        form = response.context["purpose_form"]
        self.assertEqual(form["purpose"].value(), pending_purpose)
        self.assertIn("purpose", form.errors)
        self.assertEqual(response.context["object"].purpose, "Tools")
        self.assertContains(response, self.location.physical_description, status_code=400)
        self.assertContains(response, pending_purpose, status_code=400)
        self.assertContains(response, 'data-open="true"', status_code=400)
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Tools")
        self.assertFalse(self.events().exists())

    def test_simultaneous_photo_removal_and_replacement_saves_neither(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        original_photo = self.location.overview_photo.name
        response = self.client.post(self.url, self.data(
            overview_photo=self.photo(color="red"), remove_photo="on",
        ), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("overview_photo", response.json()["errors"])
        self.location.refresh_from_db()
        self.assertEqual(self.location.overview_photo.name, original_photo)
        self.assertEqual(self.events().count(), 1)
        self.assertEqual(len([path for path in self.media_root.rglob("*") if path.is_file()]), 1)

    def test_history_database_failure_rolls_back_all_location_fields(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        original_photo = self.location.overview_photo.name
        with patch.object(ChangeLog, "save", side_effect=IntegrityError("History unavailable")):
            with self.assertRaisesMessage(IntegrityError, "History unavailable"):
                self.client.post(self.url, self.data(overview_photo=self.photo(color="red")))
            with self.assertRaisesMessage(IntegrityError, "History unavailable"):
                self.post_purpose("Must roll back")
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Tools")
        self.assertEqual(self.location.overview_photo.name, original_photo)
        self.assertTrue(self.location.overview_photo.storage.exists(original_photo))
        self.assertEqual(self.events().count(), 1)

    def test_purpose_allows_fifty_characters(self):
        response = self.post_purpose("x" * 50)
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "x" * 50)

    def test_anonymous_or_unpermitted_users_cannot_update_even_with_local_session(self):
        self.client.logout()
        for response in (self.post_purpose("Anonymous edit"), self.client.post(self.url, self.data(remove_photo="on"))):
            self.assertIn(response.status_code, (302, 403))
        reader = get_user_model().objects.create_user(username="reader")
        self.client.force_login(reader)
        session = self.client.session
        session["is_local_visit"] = True
        session.save()
        self.assertEqual(self.post_purpose("Unpermitted edit").status_code, 403)
        self.assertEqual(self.client.post(self.url, self.data(remove_photo="on")).status_code, 403)
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Tools")
        self.assertFalse(self.events().exists())

    def test_updates_require_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.get(self.purpose_url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.post_purpose("No CSRF", client=client).status_code, 403)
        self.location.refresh_from_db()
        self.assertEqual(self.location.purpose, "Tools")
        self.assertFalse(self.events().exists())

    def test_detail_remains_public_but_editor_requires_permission(self):
        self.post_purpose("Visible to everyone")
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, self.url)
        self.assertContains(detail, self.purpose_url)
        self.client.logout()
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, "Visible to everyone")
        self.assertContains(detail, self.location.physical_description)
        self.assertNotContains(detail, "change-log-heading")
        self.assertNotContains(detail, self.url)
        self.assertNotContains(detail, self.purpose_url)

    def test_detail_shows_thumbnail_and_links_full_photo(self):
        content = BytesIO()
        Image.new("RGB", (2400, 1200), "blue").save(content, format="JPEG")
        large = SimpleUploadedFile("large.jpg", content.getvalue(), content_type="image/jpeg")
        self.client.post(self.url, self.data(overview_photo=large))
        self.location.refresh_from_db()
        detail = self.client.get(self.location.get_absolute_url()).content.decode()
        link = re.search(r'<a class="location-overview-photo" href="([^"]+)"', detail).group(1)
        image = re.search(r'<a class="location-overview-photo"[^>]*>\s*(?:\{#.*?#\}\s*)?<img src="([^"]+)" width="(\d+)" height="(\d+)"', detail, re.S)
        self.assertEqual(link, self.location.overview_photo.url)
        self.assertNotEqual(image.group(1), link)
        self.assertEqual((image.group(2), image.group(3)), ("1536", "768"))

    def test_changes_need_the_permission_and_name_actors_only_for_those_allowed(self):
        self.post_purpose("Recorded change")
        self.assertEqual(self.events().get().actor_name, "overview-editor")
        # The editor may change the purpose, but seeing the changes is separate.
        self.assertNotContains(self.client.get(self.location.get_absolute_url()), "change-log-heading")
        self.client.logout()
        self.assertNotContains(self.client.get(self.location.get_absolute_url()), "change-log-heading")
        reader = get_user_model().objects.create_user(username="reader")
        reader.user_permissions.add(Permission.objects.get(codename="view_changelog"))
        self.client.force_login(reader)
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, "change-log-heading")
        self.assertContains(detail, "Recorded change")
        self.assertNotContains(detail, "overview-editor")
        detail = self.history_client().get(self.location.get_absolute_url())
        self.assertContains(detail, "Recorded change")
        self.assertContains(detail, "Tools")
        self.assertContains(detail, "overview-editor")

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

    def test_purpose_comes_first_and_the_photo_precedes_the_items(self):
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        self.location.refresh_from_db()
        unit = MeasurementUnit.objects.create(name="Piece", short="pc")
        item = Item.objects.create(name="Stored drill", measurement_unit=unit)
        ItemLocation.objects.create(item=item, location=self.location, amount=1)
        self.client.logout()
        response = self.client.get(self.location.get_absolute_url())
        heading = next(element for element in html_elements(parse_html(response.content.decode())) if element.name == "h1")
        # What it is for first, the name small after it (docs/locations.md); the code in the line below
        text = str(heading)
        self.assertLess(text.index("Tools"), text.index('<span class="loc-name">'))
        self.assertIn("Workshop", text)
        self.assertNotIn("loc-code", text)
        page = response.content.decode()
        self.assertLess(page.index("</h1>"), page.index('class="loc-code location-title-code"'))
        # the actions beside the title (data-action-row), the physical description in a grey box below
        self.assertLess(page.index('class="loc-code location-title-code"'), page.index("data-action-group"))
        self.assertLess(page.index("data-action-group"), page.index("location-summary"))
        panel = next(
            element for element in html_elements(parse_html(response.content.decode()))
            if dict(element.attributes).get("aria-labelledby") == "location-stored-heading"
        )
        contents = str(panel)
        self.assertIn("At this location …", contents)
        self.assertIn("Overview photo", contents)
        self.assertIn(self.location.overview_photo.url, contents)
        self.assertNotIn("location-overview-summary", contents)  # no separate text any more
        # The items follow in a panel of their own.
        self.assertNotIn('id="location-items-heading"', contents)
        page = response.content.decode()
        self.assertLess(page.index(self.location.overview_photo.url), page.index('id="location-items-heading"'))
        self.assertLess(page.index('id="location-items-heading"'), page.index(item.name))

    def test_camera_moves_to_the_contents_heading_while_there_is_no_photo(self):
        def layout():
            elements = list(html_elements(parse_html(self.client.get(self.location.get_absolute_url()).content.decode())))
            heading_row = next(e for e in elements if any(dict(c.attributes).get("id") == "location-stored-heading"
                                                          for c in e.children if not isinstance(c, str)))
            photo_panels = [e for e in elements if "location-photo-panel" in dict(e.attributes).get("class", "")]
            return 'data-overview-open' in str(heading_row), photo_panels
        camera_above, panels = layout()
        self.assertTrue(camera_above)
        self.assertEqual(panels, [])
        self.client.post(self.url, self.data(overview_photo=self.photo()))
        camera_above, panels = layout()
        self.assertFalse(camera_above)
        self.assertEqual(len(panels), 1)
        self.assertIn("data-overview-open", str(panels[0]))
        # The pencil follows the name and purpose inside the heading text.
        title = next(e for e in html_elements(parse_html(self.client.get(self.location.get_absolute_url()).content.decode()))
                     if "location-title-name" in dict(e.attributes).get("class", ""))
        self.assertIn('data-field-editor-open="location-purpose-editor"', str(title))

    def test_lists_and_location_choices_show_the_purpose_first(self):
        child = Location.objects.create(type=self.location.type, parent_location=self.location,
                                        name="Box 23", short_name="B23", purpose="Carp project")
        label = ('<span class="loc-label"><span class="loc-title">Carp project</span> <span class="loc-name">Box 23</span> '
                 f'<span class="loc-code">{child.unique_identifier}</span></span>')
        detail = self.client.get(self.location.get_absolute_url())
        self.assertContains(detail, label, html=True)
        listing = self.client.get(reverse("index_locations"), {"q": "Box 23"})
        self.assertContains(listing, '<span class="loc-title">Carp project</span>', html=True)
        self.assertContains(listing, f'<span class="loc-code">{child.unique_identifier}</span>', html=True)
        for name in ("location-autocomplete", "parent_location_autocomplete"):
            with self.subTest(autocomplete=name):
                # the frontend's fields (widgets.LocationSelect): HTML, with where it is below
                result = self.client.get(reverse(name), {"q": "carp", "html": "1"}).json()["results"][0]
                self.assertInHTML(label, result["text"])
                self.assertIn(f'<span class="loc-where">{self.location.title}</span>', result["text"])
                self.assertInHTML(label, result["selected_text"])
                # the admin's: text with the path
                results = self.client.get(reverse(name), {"q": "carp"}).json()["results"]
                self.assertEqual([result["text"] for result in results], [f"{child.descriptive_identifier}: Carp project"])
        # Escaped, also as the text of a chosen option, which the field shows as HTML.
        child.purpose = "<b>Carp</b>"
        child.save()
        result = self.client.get(reverse("location-autocomplete"), {"q": "carp", "html": "1"}).json()["results"][0]
        self.assertIn("&lt;b&gt;Carp&lt;/b&gt;", result["text"])
        from django import forms as django_forms
        from ..widgets import LocationSelect

        class Choose(django_forms.Form):
            location = django_forms.ModelChoiceField(Location.objects.all(), widget=LocationSelect(url="location-autocomplete"))

        rendered = str(Choose(initial={"location": child.pk})["location"])
        self.assertIn("html=1", rendered)
        self.assertIn("data-html", rendered)
        # the option's text is the label's HTML, escaped like any text: its own escaping stays
        self.assertIn("&amp;lt;b&amp;gt;Carp&amp;lt;/b&amp;gt;", rendered)
        self.assertIn("&lt;span class=&quot;loc-code&quot;&gt;", rendered)
        # Printed labels and the stored path keep the plain name.
        self.assertNotIn("Carp project", child.descriptive_identifier)

    def test_public_metadata_modal_opens_beside_the_physical_description(self):
        self.client.logout()
        label_url = "https://example.com/location-label.png"
        with patch.object(Location, "label_preview_url", new=lambda location: label_url):
            response = self.client.get(self.location.get_absolute_url())
        elements = list(html_elements(parse_html(response.content.decode())))
        metadata = next(element for element in elements if dict(element.attributes).get("id") == "location-metadata")
        self.assertIn("modal", dict(metadata.attributes).get("class", "").split())
        self.assertEqual(dict(metadata.attributes).get("aria-hidden"), "true")
        self.assertIn(self.location.physical_description, str(metadata))
        self.assertNotIn(label_url, str(metadata))  # no label preview in the details
        description = next(element for element in elements if "location-header-description" in dict(element.attributes).get("class", "").split())
        self.assertIn(self.location.physical_description, str(description))
        trigger = next(element for element in html_elements(description) if dict(element.attributes).get("data-bs-target") == "#location-metadata")
        self.assertEqual(trigger.name, "button")
        self.assertEqual(dict(trigger.attributes).get("data-bs-toggle"), "modal")
        self.assertEqual(dict(trigger.attributes).get("aria-label"), "Location details")  # the (i) in the grey box
        # The path is in the breadcrumb, and in the details, not in the heading.
        path = next(element for element in elements if "location-path" in dict(element.attributes).get("class", "").split())
        self.assertIn(path, list(html_elements(metadata)))
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

    def test_purpose_html_is_escaped(self):
        self.post_purpose('<img src=x onerror="alert(1)">')
        self.client.logout()
        for client in (self.client, self.history_client()):
            with self.subTest(client=client):
                response = client.get(self.location.get_absolute_url())
                self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
                self.assertNotContains(response, '<img src=x onerror="alert(1)">')

    def test_history_keeps_actor_snapshot_after_account_is_deleted(self):
        self.post_purpose("Recorded change")
        event = self.events().get()
        actor_name = event.actor_name
        self.client.logout()
        self.user.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_name, actor_name)
        self.assertContains(self.history_client().get(self.location.get_absolute_url()), actor_name)

    def test_the_page_shows_the_last_changes_newest_first(self):
        for index in range(7):
            self.post_purpose(f"Change {index}")
        client = self.history_client()
        shown = [entry["entry"].changes[0]["after"] for entry in
                 client.get(self.location.get_absolute_url()).context["change_log_entries"]]
        self.assertEqual(shown, [f"Change {index}" for index in (6, 5, 4, 3, 2)])
        with override_settings(CHANGE_LOG_SHOWN=2):
            response = client.get(self.location.get_absolute_url())
            self.assertEqual(len(response.context["change_log_entries"]), 2)
            self.assertContains(response, "The last 2 changes.")
        with override_settings(CHANGE_LOG_SHOWN=0):
            self.assertNotContains(client.get(self.location.get_absolute_url()), "change-log-heading")

    def test_admin_changes_record_parent_and_inline_overview_history(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        child = Location.objects.create(
            type=self.location.type, name="Child", short_name="CHILD",
            parent_location=self.location, purpose="Original child",
        )
        response = self.client.post(reverse("admin:inventory_location_change", args=[self.location.pk]), {
            "id": self.location.pk, "name": self.location.name, "short_name": self.location.short_name,
            "type": self.location.type_id, "purpose": "Admin overview",
            "physical_description": self.location.physical_description,
            "children-TOTAL_FORMS": "1", "children-INITIAL_FORMS": "1",
            "children-MIN_NUM_FORMS": "0", "children-MAX_NUM_FORMS": "1000",
            "number_ranges-TOTAL_FORMS": "0", "number_ranges-INITIAL_FORMS": "0",
            "former_codes-TOTAL_FORMS": "0", "former_codes-INITIAL_FORMS": "0",
            "change_log-TOTAL_FORMS": "0", "change_log-INITIAL_FORMS": "0",
            "children-0-id": child.pk, "children-0-parent_location": self.location.pk,
            "children-0-type": child.type_id, "children-0-name": child.name,
            "children-0-short_name": child.short_name, "children-0-purpose": "Updated child",
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.location.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(self.location.purpose, "Admin overview")
        self.assertEqual(child.purpose, "Updated child")
        parent_event = self.events().get()
        child_event = ChangeLog.objects.get(location=child, action=ChangeLog.Action.CHANGED)
        self.assertEqual(self.changed(parent_event, "purpose"), ("Tools", "Admin overview"))
        self.assertEqual(self.changed(child_event, "purpose"), ("Original child", "Updated child"))
        self.assertEqual(parent_event.actor_id, self.user.pk)
        self.assertEqual(child_event.actor_id, self.user.pk)
        self.assertEqual({parent_event.source, child_event.source}, {ChangeLog.Source.ADMIN})

    def test_deleted_locations_cannot_be_viewed_or_updated(self):
        Location.objects.filter(pk=self.location.pk).update(is_deleted=True)
        self.assertEqual(self.client.get(self.location.get_absolute_url()).status_code, 404)
        self.assertEqual(self.post_purpose("Archived edit").status_code, 404)
        self.assertEqual(self.client.post(self.url, self.data(remove_photo="on")).status_code, 404)
        self.assertFalse(self.events().exists())

    def test_location_search_and_autocompletes_match_purpose_and_physical_description(self):
        Location.objects.filter(pk=self.location.pk).update(purpose="Electric tools")
        Location.objects.create(
            type=self.location.type, name="Unrelated", short_name="OTHER", purpose="No match",
        )
        deleted = Location.objects.create(
            type=self.location.type, name="Deleted", short_name="DELETED",
            purpose="Electric tools", physical_description="West wall", is_deleted=True,
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
            self.assertEqual(location.purpose, "")
            self.assertFalse(location.overview_photo)
            self.assertFalse(apps.get_model("inventory", "ChangeLog").objects.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
