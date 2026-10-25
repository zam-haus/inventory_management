from decimal import Decimal
from io import BytesIO
from unittest import mock
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Team
from label_printing import services as print_services
from label_printing.devices.run import Result
from label_printing.models import PrintJob
from label_printing.tests.helpers import create_printers
from ..actor import acting_as
from .. import change_log
from ..change_log import actor_label
from ..templatetags.change_log import field_label
from ..label_ids import services as label_ids
from ..label_ids.testing import SETTINGS, make_id
from ..models import ChangeLog, Item, ItemFile, ItemImage, ItemLocation, Location, LocationType, MeasurementUnit, UniqueItem


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="inventory", codename__in=codenames))


def photo():
    content = BytesIO()
    Image.new("RGB", (40, 30), "blue").save(content, format="PNG")
    return SimpleUploadedFile("photo.png", content.getvalue(), content_type="image/png")


@override_settings(**SETTINGS)
class ChangeLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        cls.room = LocationType.objects.create(name="Room", unique=True, moveable=True)
        cls.workshop = Location.objects.create(type=cls.room, name="Workshop", short_name="WS", purpose="Tools")
        cls.store = Location.objects.create(type=cls.room, name="Store", short_name="ST")
        User = get_user_model()
        # Invented people only.
        cls.member = User.objects.create_user(username="alex", first_name="Alex", last_name="Example")
        grant(cls.member, "change_item", "add_itemimage", "add_itemfile", "change_location")
        cls.viewer = User.objects.create_user(username="viewer")
        grant(cls.viewer, "view_changelog")
        cls.active = User.objects.create_user(username="active")
        grant(cls.active, "view_changelog", "view_changelog_actor")
        cls.insider = User.objects.create_user(username="insider")
        grant(cls.insider, "view_changelog", "view_internal_details")

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.item = Item.objects.create(name="Drill", last_purchase_price=Decimal("80.00"))

    def entries(self, **filters):
        return ChangeLog.objects.filter(**filters).order_by("pk")

    def panel(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_creation_and_field_changes_of_an_item(self):
        created = self.entries(item=self.item).get()
        self.assertEqual((created.action, created.subject_label, created.source), ("created", "Drill", "other"))
        with acting_as(self.member):
            self.item.description = "Cordless"
            self.item.last_purchase_price = Decimal("75.00")
            self.item.save()
        changed = self.entries(item=self.item, action="changed").get()
        self.assertEqual(changed.actor, self.member)
        self.assertEqual(changed.changes, [
            {"field": "description", "before": "", "after": "Cordless", "internal": False},
            {"field": "last_purchase_price", "before": "80.00", "after": "75.00", "internal": True},
        ])
        self.item.save()  # unchanged: no entry
        self.assertEqual(self.entries(item=self.item).count(), 2)

    def test_new_stock_has_no_reason_unless_given(self):
        ItemLocation.objects.create(item=self.item, location=self.workshop, amount=3)
        stored = self.entries(action="stock").get()
        self.assertEqual((stored.reason, stored.sale_value, stored.details["added"], stored.amount_after),
                         ("", None, True, Decimal(3)))

    def test_the_web_form_is_the_source(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("quick_item_photo", args=[self.item.pk]), {"image": photo()})
        self.assertEqual(response.status_code, 302)
        attached = self.entries(action="attached").get()
        self.assertEqual((attached.item, attached.source, attached.actor, attached.subject_type),
                         (self.item, "web", self.member, "itemimage"))
        ItemImage.objects.get().delete()
        self.assertEqual(self.entries(action="detached").get().item, self.item)

    def test_internal_files_are_internal(self):
        ItemFile.objects.create(item=self.item, description="Invoice", internal=True,
                                file=SimpleUploadedFile("invoice.pdf", b"%PDF-1.4"))
        # Shown by name, as on the page; only the data export leaves the name out.
        self.assertEqual(self.entries(action="attached").get().details, {"internal": True})
        self.assertContains(self.panel(self.viewer, self.item.get_absolute_url()), "Attachment added</strong>: Invoice")

    def test_a_quick_item_rename_is_logged(self):
        entry = ItemLocation.objects.create(item=Item.objects.create(name="Glue"), location=self.workshop)
        self.client.force_login(get_user_model().objects.create_superuser(username="admin"))
        self.client.post(reverse("quick_item_update", args=[entry.pk]), {"name": "Wood glue"})
        changed = self.entries(item=entry.item, action="changed").get()
        self.assertEqual(changed.changes[0]["after"], "Wood glue")

    def test_location_moves_show_on_both_pages(self):
        box = Location.objects.create(type=self.room, name="Box", short_name="BOX", parent_location=self.workshop)
        self.assertEqual(self.entries(location=box).get().other_location, self.workshop)  # created inside
        self.client.force_login(self.member)
        self.client.post(reverse("location_move", args=[box.pk]), {"parent_location": self.store.pk, "id": box.pk})
        moved = self.entries(action="moved").get()
        self.assertEqual((moved.location, moved.other_location, moved.actor), (box, self.workshop, self.member))
        self.assertEqual(moved.changes[0]["field"], "parent_location")
        self.assertContains(self.panel(self.viewer, self.workshop.get_absolute_url()), "Box")

    def test_soft_deletion_and_restoring(self):
        box = Location.objects.create(type=self.room, name="Box", short_name="BOX", parent_location=self.workshop)
        box.delete()
        deleted = self.entries(action="deleted").get()
        self.assertEqual((deleted.location, deleted.other_location), (box, self.workshop))
        box.is_deleted = False
        box.save()
        self.assertEqual(self.entries(action="restored").get().location, box)

    def test_responsible_teams_join_the_admin_entry(self):
        team = Team.objects.create(group=Group.objects.create(name="Woodworking"))
        self.client.force_login(get_user_model().objects.create_superuser(username="admin"))
        response = self.client.post(reverse("admin:inventory_location_change", args=[self.workshop.pk]), {
            "id": self.workshop.pk, "name": "Workshop", "short_name": "WS", "type": self.room.pk,
            "purpose": "Wood tools", "physical_description": "", "responsible_teams": [team.pk],
            **{f"{prefix}-{key}": "0" for prefix in ("children", "number_ranges", "former_codes", "change_log")
               for key in ("TOTAL_FORMS", "INITIAL_FORMS")},
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        changed = self.entries(location=self.workshop, action="changed").get()
        self.assertEqual(changed.source, "admin")
        self.assertEqual([(change["field"], change["after"]) for change in changed.changes],
                         [("purpose", "Wood tools"), ("responsible_teams", "Woodworking")])

    def test_unique_items_and_label_ids(self):
        drill = Item.objects.create(name="Saw", kind=Item.Kind.UNIQUE)
        saw = UniqueItem.objects.create(item=drill, location=self.workshop)
        lid = label_ids.claim(make_id("K7R4X").code, saw, self.member)
        label_ids.retire(lid.code, self.member)
        events = [entry.details["event"] for entry in self.entries(unique_item=saw, action="label_id")]
        self.assertEqual(events, ["assigned", "retired"])
        content = self.panel(self.viewer, saw.get_absolute_url()).content.decode()
        self.assertIn("K7R-4XD retired", content)

    def test_printed_labels(self):
        zebra, labels, _brother, _tape = create_printers()
        ItemLocation.objects.create(item=self.item, location=self.workshop, amount=3)

        def job(**fields):
            return PrintJob.objects.create(
                printer=zebra, medium=labels, layout_key="design:0", subject_type="item", copies=2,
                user=self.member, status=PrintJob.Status.PROCESSING,
                snapshot=[{"type": "item", "id": self.item.pk, "location_id": self.workshop.pk}], **fields)
        done = job()
        print_services.finish(done, Result("done"))
        print_services.finish(done, Result("done"))  # reported twice: logged once
        printed = self.entries(action="printed").get()
        self.assertEqual((printed.item, printed.location, printed.actor, printed.source),
                         (self.item, self.workshop, self.member, "print"))
        self.assertEqual((printed.details["printer"], printed.details["copies"]), ("Zebra Lager", 2))
        print_services.finish(job(), Result("failed", "paper_out"))
        self.assertEqual(self.entries(action="printed").count(), 1)
        self.assertContains(self.panel(self.viewer, self.workshop.get_absolute_url()), "Label printed")

    def test_who_sees_what(self):
        with acting_as(self.member):
            self.item.description = "Cordless"
            self.item.last_purchase_price = Decimal("75.00")
            self.item.save()
        url = self.item.get_absolute_url()
        self.assertNotContains(self.client.get(url), "change-log-heading")  # guests
        self.assertNotContains(self.panel(self.member, url), "change-log-heading")  # no permission
        viewer = self.panel(self.viewer, url).content.decode()
        self.assertIn("<ins>Cordless</ins>", viewer)
        self.assertNotIn("75.00", viewer)
        self.assertNotIn("Alex", viewer)
        self.assertIn("Alex E. (alex)", self.panel(self.active, url).content.decode())
        self.assertIn("<ins>75.00</ins>", self.panel(self.insider, url).content.decode())

    def test_actor_label(self):
        self.assertEqual(actor_label(self.member), "Alex E. (alex)")
        self.assertEqual(actor_label(self.viewer), "viewer")

    def test_the_migration_grants_the_local_and_the_actor_group(self):
        local = Group.objects.get(name=settings.LOCAL_GROUP_NAME)
        active = Group.objects.get(name=settings.CHANGE_LOG_ACTOR_GROUP)
        self.assertEqual(set(local.permissions.filter(codename__contains="changelog").values_list("codename", flat=True)),
                         {"view_changelog"})
        self.assertEqual(set(active.permissions.values_list("codename", flat=True)),
                         {"view_changelog", "view_changelog_actor"})

    def test_every_tracked_field_exists(self):
        self.assertEqual(change_log.missing_fields(), [])
        self.assertEqual(change_log.check_tracked_fields(None), [])

    def test_a_vanished_field_is_left_out_with_a_warning(self):
        fields, internal = change_log.TRACKED["item"]
        tracked = {**change_log.TRACKED, "item": (("colour", *fields), internal)}
        with mock.patch.object(change_log, "TRACKED", tracked):
            change_log._fields.cache_clear()
            self.addCleanup(change_log._fields.cache_clear)
            self.assertEqual([warning.id for warning in change_log.check_tracked_fields(None)], ["inventory.W001"])
            with self.assertLogs("inventory.change_log", "WARNING") as logged:
                self.item.name = "Hammer drill"
                self.item.save()  # still saved and logged
            self.assertIn("item.colour", logged.output[0])
        self.assertEqual(self.entries(item=self.item, action="changed").get().changes[0]["after"], "Hammer drill")

    def test_older_entries_keep_labels_of_former_fields(self):
        self.assertEqual(field_label("location", "summary"), "summary")
        with mock.patch.dict(change_log.FORMER_FIELDS, {("location", "summary"): "Zusammenfassung"}):
            self.assertEqual(field_label("location", "summary"), "Zusammenfassung")
        self.assertEqual(field_label("vanished", "name"), "name")
