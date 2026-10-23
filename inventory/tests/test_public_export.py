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
from ..models import (Item, ItemFile, Location, LocationHistory, StockChange, UniqueItem, UniqueItemEvent)


class ExportFixture(InventoryFixture):
    def create_export_data(self):
        self.create_inventory()
        User = get_user_model()
        # Invented people only.
        self.owner = User.objects.create_user(username="robinprivate", first_name="Robin", last_name="Private",
                                              email="robin@example.org")
        self.unique_type = Item.objects.create(name="Fire extinguisher", kind=Item.Kind.UNIQUE,
                                               measurement_unit=self.unit)
        self.unique_item = UniqueItem.objects.create(
            item=self.unique_type, location=self.location, notes="Checked yearly", owner_user=self.owner,
            owner_first_name="Robin", owner_contact="+49 170 0000000", responsible_user=self.owner)
        self.zam_item = UniqueItem.objects.create(item=self.unique_type, location=self.location)
        UniqueItemEvent.objects.create(unique_item=self.unique_item, type=UniqueItemEvent.Type.CREATED,
                                       actor=self.owner, to_owner_user=self.owner, to_owner_name="Robin",
                                       to_owner_contact="robin@example.org", note="Lent by Robin Private")
        StockChange.objects.create(actor=self.owner, direction="out", reason="sold", note="sold to Robin",
                                   item=self.item, item_name="Drill", location=self.location,
                                   location_name="Workshop", unit="pc")
        LocationHistory.objects.create(location=self.location, actor=self.owner, actor_name="Robin Private")
        ItemFile.objects.create(item=self.item, description="Manual",
                                file=ContentFile(b"%PDF-1.4 manual", name="manual.pdf"))
        ItemFile.objects.create(item=self.item, description="Invoice", internal=True,
                                file=ContentFile(b"%PDF-1.4 invoice", name="invoice.pdf"))

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

    def test_unreviewed_field_stops_the_export(self):
        exported = dict(public_export.EXPORTED_MODELS, **{"inventory.item": {"keep": "name"}})
        with mock.patch.object(public_export, "EXPORTED_MODELS", exported), \
                self.assertRaisesMessage(CommandError, "field inventory.item.description is not reviewed"):
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
        history = next(f for (model, _pk), f in rows.items() if model == "inventory.locationhistory")
        self.assertEqual((history["actor"], history["actor_name"]), (None, public_export.REDACTED))

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
        self.assertIn("1 kept texts contain", stdout)

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
