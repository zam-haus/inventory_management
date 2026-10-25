import json
import shutil
import tarfile
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase, override_settings

from .. import public_export
from ..label_ids.testing import SETTINGS, InventoryFixture, make_id
from ..actor import acting_as
from ..models import ChangeLog, Item, ItemFile, LabelId, Location, UniqueItem


class ExportFixture(InventoryFixture):
    def create_export_data(self):
        self.create_inventory()
        User = get_user_model()
        # Invented people only.
        self.owner = User.objects.create_user(username="robinprivate", first_name="Robin", last_name="Private",
                                              email="robin@example.org")
        self.unique_type = Item.objects.create(name="Fire extinguisher", kind=Item.Kind.UNIQUE,
                                               measurement_unit=self.unit)
        with acting_as(self.owner):  # logged as who made the changes
            self.unique_item = UniqueItem.objects.create(
                item=self.unique_type, location=self.location, notes="Checked yearly", owner_first_name="Robin")
            self.unique_item.owner_first_name = ""
            self.unique_item.owner_user, self.unique_item.responsible_user = self.owner, self.owner
            self.unique_item.owner_contact = "+49 170 0000000"
            self.unique_item.save()
            self.location.purpose = "Drills"
            self.location.save()
            ItemFile.objects.create(item=self.item, description="Manual",
                                    file=ContentFile(b"%PDF-1.4 manual", name="manual.pdf"))
            ItemFile.objects.create(item=self.item, description="Invoice of Robin Private", internal=True,
                                    file=ContentFile(b"%PDF-1.4 invoice", name="invoice.pdf"))
        self.zam_item = UniqueItem.objects.create(item=self.unique_type, location=self.location)
        ChangeLog.objects.create(actor=self.owner, actor_name="robinprivate", action=ChangeLog.Action.STOCK,
                                 reason="sale", note="sold to Robin", subject_type="itemlocation",
                                 subject_label="Drill", item=self.item, location=self.location)

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out)

    def export(self, *args):
        stdout, stderr = StringIO(), StringIO()
        call_command("export_public_data", *args, stdout=stdout, stderr=stderr)
        return stdout.getvalue(), stderr.getvalue()


@override_settings(**SETTINGS)
class PublicExportTests(ExportFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.create_export_data()
        # Label IDs are never deleted (database trigger), so only here and not in the flushed import tests.
        make_id("K7R4X", created_by=self.owner, note="printed by Robin")

    def rows(self, directory):
        return json.loads((directory / "data.json").read_text())

    def test_every_model_and_field_is_reviewed(self):
        public_export.check_review()

    def test_personal_looking_field_stops_the_export(self):
        spec = public_export.EXPORTED_MODELS["inventory.changelog"]
        exported = dict(public_export.EXPORTED_MODELS, **{"inventory.changelog": {"replace": {"note": spec["replace"]["note"]}}})
        with mock.patch.object(public_export, "EXPORTED_MODELS", exported), \
                self.assertRaisesMessage(CommandError, "field inventory.changelog.actor looks personal"):
            self.export(str(self.out / "export"))

    def test_other_fields_are_kept_without_listing_them(self):
        self.assertEqual(public_export.EXPORTED_MODELS["inventory.location"], {})
        self.assertFalse(public_export.looks_personal(Item, "description"))
        self.assertFalse(public_export.looks_personal(Item, "last_purchase_price"))  # internal, so replaced anyway
        for model, name in ((ChangeLog, "actor"), (UniqueItem, "owner_contact"), (LabelId, "created_by")):
            self.assertTrue(public_export.looks_personal(model, name), name)

    def test_new_model_stops_the_export(self):
        exported = {label: spec for label, spec in public_export.EXPORTED_MODELS.items() if label != "inventory.item"}
        with mock.patch.object(public_export, "EXPORTED_MODELS", exported), \
                self.assertRaisesMessage(CommandError, "model inventory.item is neither exported nor excluded"):
            self.export(str(self.out / "export"))

    def test_no_personal_data(self):
        self.export(str(self.out / "export"))
        data = (self.out / "export" / "data.json").read_text()
        for personal in ("Robin", "Private", "robin@example.org", "robinprivate", "+49 170", str(self.owner.pk)):
            self.assertNotIn(personal, data)
        models = {row["model"] for row in self.rows(self.out / "export")}
        self.assertNotIn("accounts.user", models)
        self.assertNotIn("sessions.session", models)

    def test_owner_and_actor_stay_recognisable(self):
        self.export(str(self.out / "export"))
        rows = {(row["model"], row.get("pk")): row["fields"] for row in self.rows(self.out / "export")}
        owned = rows[("inventory.uniqueitem", self.unique_item.pk)]
        self.assertEqual((owned["owner_first_name"], owned["owner_contact"], owned["owner_user"]),
                         (public_export.REDACTED, "", None))
        self.assertEqual(rows[("inventory.uniqueitem", self.zam_item.pk)]["owner_first_name"], "")
        self.assertEqual(owned["notes"], "Checked yearly")  # public on the website
        log = [fields for (model, _pk), fields in rows.items() if model == "inventory.changelog"]
        self.assertEqual({(fields["actor"], fields["actor_name"], fields["note"]) for fields in log},
                         {(None, public_export.REDACTED, ""), (None, "", "")})
        changes = {change["field"]: change for fields in log for change in fields["changes"]}
        self.assertEqual(set(changes), {"purpose"})  # owners and internal values left out
        self.assertEqual(changes["purpose"]["after"], "Drills")
        attached = {fields["subject_label"] for fields in log if fields["action"] == "attached"}
        self.assertEqual(attached, {"Manual", public_export.REDACTED})  # the internal file's name is left out

    def test_internal_documents_are_left_out(self):
        self.export(str(self.out / "export"))
        files = [row["fields"]["description"] for row in self.rows(self.out / "export")
                 if row["model"] == "inventory.itemfile"]
        self.assertEqual(files, ["Manual"])
        exported = [p.name for p in (self.out / "export" / "media").rglob("*") if p.is_file()]
        self.assertEqual(exported, ["manual.pdf"])

    def test_names_in_kept_texts_are_reported(self):
        self.item.description = "Donated by Robin Private"
        self.item.save()
        stdout, stderr = self.export(str(self.out / "export"))
        self.assertIn(f"check inventory.item {self.item.pk} description: contains 'Robin Private'", stderr)
        # Also in the change log, which holds the new description.
        self.assertIn("check inventory.changelog", stderr)
        self.assertIn("2 kept texts contain", stdout)

    def test_archive(self):
        self.export(str(self.out / "export.tar"))
        with tarfile.open(self.out / "export.tar") as tar:
            names = tar.getnames()
        self.assertIn("data.json", names)
        self.assertIn("export-info.json", names)
        manual = ItemFile.objects.get(internal=False)
        self.assertEqual([n for n in names if n.startswith("media/")], [f"media/{manual.file.name}"])

    def test_without_media(self):
        self.export(str(self.out / "export"), "--no-media")
        self.assertFalse((self.out / "export" / "media").exists())

    def test_existing_target(self):
        (self.out / "export").mkdir()
        with self.assertRaisesMessage(CommandError, "exists already"):
            self.export(str(self.out / "export"))


@override_settings(**SETTINGS)
class PublicImportTests(ExportFixture, TransactionTestCase):
    def test_round_trip(self):
        self.create_export_data()
        self.export(str(self.out / "export.tar"))
        call_command("flush", interactive=False, verbosity=0)
        shutil.rmtree(self.media)
        call_command("import_public_data", str(self.out / "export.tar"), stdout=StringIO(), verbosity=0)
        self.assertEqual(Location.objects.get().name, "Workshop")
        owned = UniqueItem.objects.get(owner_first_name=public_export.REDACTED)
        self.assertTrue(owned.has_owner)
        self.assertFalse(get_user_model().objects.exists())
        manual = ItemFile.objects.get()
        self.assertEqual(manual.file.read(), b"%PDF-1.4 manual")

    def test_refuses_a_filled_database(self):
        self.create_export_data()
        self.export(str(self.out / "export"))
        with self.assertRaisesMessage(CommandError, "already holds an inventory"):
            call_command("import_public_data", str(self.out / "export"), stdout=StringIO())

    def test_refuses_an_export_of_newer_code(self):
        self.create_export_data()
        self.export(str(self.out / "export"), "--no-media")
        info_path = self.out / "export" / "export-info.json"
        info = json.loads(info_path.read_text())
        info["migrations"].append("inventory.9999_future")
        info_path.write_text(json.dumps(info))
        call_command("flush", interactive=False, verbosity=0)
        with self.assertRaisesMessage(CommandError, "newer version of the code"):
            call_command("import_public_data", str(self.out / "export"), stdout=StringIO())
