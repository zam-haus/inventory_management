import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from ..icons import icon
from ..models import ItemFile, ItemImage, ItemLocation, UniqueItem
from .test_unique_items import UniqueItemFixture, grant
from ..label_ids import services
from ..label_ids.testing import SETTINGS, make_id, local_group


def png(color="red"):
    content = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(content, "PNG")
    return SimpleUploadedFile(f"{color}.png", content.getvalue(), content_type="image/png")


class MediaMixin:
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)


@override_settings(**SETTINGS)
class DocumentTests(MediaMixin, UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def setUp(self):
        super().setUp()
        self.manual = ItemFile.objects.create(item=self.extinguisher, description="Manual",
                                              file=ContentFile(b"%PDF-1.4 manual", name="manual.pdf"))
        self.invoice = ItemFile.objects.create(item=self.extinguisher, unique_item=self.unique_item, description="Invoice", internal=True,
                                                     file=ContentFile(b"%PDF-1.4 invoice", name="invoice.pdf"))

    def test_stored_in_unguessable_folders(self):
        self.assertRegex(self.manual.file.name, r"^documents/[0-9a-f]{32}/manual\.pdf$")
        self.assertNotEqual(self.manual.file.name.split("/")[1], self.invoice.file.name.split("/")[1])

    def test_public_documents(self):
        response = self.client.get(self.manual.get_absolute_url())
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 manual")
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        page = self.client.get(self.extinguisher.get_absolute_url())
        self.assertContains(page, f'<a href="{self.manual.get_absolute_url()}">Manual</a>', html=True)
        self.assertNotContains(page, self.manual.file.name)

    def test_internal_documents_are_listed_without_link(self):
        url = self.invoice.get_absolute_url()
        for user in (None, self.member):
            if user:
                self.client.force_login(user)
            page = self.client.get(self.unique_item.get_absolute_url())
            self.assertContains(page, "Invoice")
            self.assertNotContains(page, url)
            self.assertNotContains(page, self.invoice.file.name.split("/")[1])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_internal_documents_with_permission(self):
        self.client.force_login(self.insider)
        self.assertContains(self.client.get(self.unique_item.get_absolute_url()), f'href="{self.invoice.get_absolute_url()}"')
        response = self.client.get(self.invoice.get_absolute_url())
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 invoice")
        self.assertIn("no-store", response["Cache-Control"])

    def test_active_content_is_downloaded(self):
        page = ItemFile.objects.create(item=self.extinguisher, file=ContentFile(b"<script>x</script>", name="x.html"))
        self.assertTrue(self.client.get(page.get_absolute_url())["Content-Disposition"].startswith("attachment"))

    def test_edit_form_hides_internal_documents(self):
        self.client.force_login(self.member)
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        response = self.client.get(url)
        # The item's public manual and an empty row; the internal invoice is left out.
        files = response.context["inlines"][1]
        self.assertEqual([form.instance.pk for form in files.forms], [self.manual.pk, None])
        self.assertNotContains(response, "Invoice")
        data = {"location": self.location.pk, "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0",
                "files-TOTAL_FORMS": "1", "files-INITIAL_FORMS": "0",
                "files-0-description": "Receipt", "files-0-internal": "on", "files-0-level": "unique",
                "files-0-file": SimpleUploadedFile("receipt.pdf", b"%PDF-1.4", content_type="application/pdf")}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        receipt = ItemFile.objects.get(description="Receipt")
        self.assertEqual((receipt.internal, receipt.unique_item), (True, self.unique_item))
        self.assertTrue(ItemFile.objects.get(pk=self.invoice.pk).internal)
        self.client.force_login(self.insider)
        self.assertContains(self.client.get(url), "Invoice")


@override_settings(**SETTINGS)
class PhotoTests(MediaMixin, UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def photo_data(self, photos, **extra):
        data = {"location": self.location.pk, "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0",
                "images-TOTAL_FORMS": str(len(photos)), "images-INITIAL_FORMS": str(sum(1 for p in photos if p.get("id")))}
        for index, photo in enumerate(photos):
            data.update({f"images-{index}-{key}": value for key, value in {"level": "unique", **photo}.items()})
        return {**data, **extra}

    def test_one_primary_per_owner(self):
        ItemImage.objects.create(item=self.item, image="items/a.jpg", is_primary=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemImage.objects.create(item=self.item, image="items/b.jpg", is_primary=True)
        ItemImage.objects.create(item=self.other_item, image="items/c.jpg", is_primary=True)

    def test_primary_comes_first(self):
        first = ItemImage.objects.create(item=self.item, image="items/a.jpg")
        primary = ItemImage.objects.create(item=self.item, image="items/b.jpg", is_primary=True)
        self.assertEqual(list(self.item.itemimage_set.all()), [primary, first])

    def test_choosing_another_primary(self):
        self.client.force_login(self.member)
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        a = ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item, image=png("red"), is_primary=True)
        b = ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item, image=png("blue"))
        # The newer photo becomes primary while the older one is still saved as primary.
        response = self.client.post(url, self.photo_data([{"id": b.pk, "is_primary": "on"}, {"id": a.pk}]))
        self.assertEqual(response.status_code, 302, response.context and [f.errors for f in response.context["inlines"]] + [response.context["form"].errors])
        self.assertEqual(list(self.unique_item.images.values_list("pk", "is_primary")), [(b.pk, True), (a.pk, False)])
        # A new photo marked primary replaces the current one.
        response = self.client.post(url, self.photo_data([{"id": b.pk, "is_primary": "on"}, {"id": a.pk},
                                                          {"image": png("green"), "is_primary": "on"}]))
        self.assertEqual(response.status_code, 200)  # two primaries chosen
        response = self.client.post(url, self.photo_data([{"id": b.pk}, {"id": a.pk},
                                                          {"image": png("green"), "is_primary": "on"}]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.unique_item.images.get(is_primary=True).description, "")
        self.assertEqual(self.unique_item.images.filter(is_primary=True).count(), 1)

    def test_own_photos_come_before_the_items(self):
        ItemImage.objects.create(item=self.extinguisher, image=png("red"), description="Type photo")
        ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item, image=png("blue"), description="Dent on the side")
        for url in (self.unique_item.get_absolute_url(), self.location.get_absolute_url()):
            content = self.client.get(url).content.decode()
            self.assertLess(content.index("Dent on the side"), content.index("Type photo"), url)


@override_settings(**SETTINGS)
class ItemListTests(UniqueItemFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.second = UniqueItem.objects.create(item=cls.extinguisher, location=cls.shelf)
        cls.gone = UniqueItem.objects.create(item=cls.extinguisher, location=cls.shelf)
        cls.gone.dispose(UniqueItem.DisposalReason.SCRAPPED)

    def test_ids_and_locations_in_the_location_column(self):
        response = self.client.get(reverse("index_items"))
        self.assertContains(response, f'<a href="{self.unique_item.get_absolute_url()}">K7R-4XD</a>', html=True)
        self.assertContains(response, f'<a href="{self.second.get_absolute_url()}">#{self.second.pk}</a>', html=True)
        self.assertContains(response, f'title="{self.shelf.descriptive_identifier}"')
        self.assertNotContains(response, self.gone.get_absolute_url())

    def test_photos_of_unique_items_are_listed(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        with override_settings(MEDIA_ROOT=media):
            ItemImage.objects.create(item=self.extinguisher, image=png("red"), description="Type photo")
            ItemImage.objects.create(item=self.extinguisher, unique_item=self.second, image=png("blue"), description="Dent")
            ItemImage.objects.create(item=self.extinguisher, unique_item=self.gone, image=png("green"), description="Gone")
            content = self.client.get(reverse("index_items")).content.decode()
            self.assertLess(content.index('alt="Type photo"'), content.index('alt="Dent"'))
            self.assertNotIn('alt="Gone"', content)
            # More photos do not mean more queries (thumbnails are created on the first view).
            url = reverse("index_items")
            self.client.get(url)
            before = self.count_queries(url)
            ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item, image=png("yellow"))
            self.client.get(url)
            self.assertEqual(self.count_queries(url), before)

    def count_queries(self, url):
        queries = []
        with connection.execute_wrapper(lambda execute, sql, *args: queries.append(sql) or execute(sql, *args)):
            self.client.get(url)
        return len(queries)

    def test_search_by_location_of_unique_items(self):
        response = self.client.get(reverse("index_items"), {"q": "Shelf"})
        self.assertEqual(list(response.context["object_list"]), [self.extinguisher])
        ItemLocation.objects.create(item=self.item, location=self.location, amount=Decimal(3))
        names = [item.name for item in self.client.get(reverse("index_items"), {"q": "Workshop"}).context["object_list"]]
        self.assertEqual(sorted(names), ["Drill", "Fire extinguisher"])


class DocumentMigrationTests(TransactionTestCase):
    def test_existing_files_move_to_document_folders(self):
        before = [("inventory", "0022_zamid_triggers_and_claim")]
        after = [("inventory", "0023_unique_items_squashed_0031")]
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        with override_settings(MEDIA_ROOT=media):
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            try:
                apps = executor.loader.project_state(before).apps
                unit = apps.get_model("inventory", "MeasurementUnit").objects.create(name="Piece", short="pc")
                item = apps.get_model("inventory", "Item").objects.create(name="Saw", measurement_unit=unit)
                old = default_storage.save(f"items/{item.pk}/2026-10-11T21:05:03.123456_manual.pdf", ContentFile(b"%PDF"))
                document = apps.get_model("inventory", "ItemFile").objects.create(item=item, file=old)
                executor = MigrationExecutor(connection)
                executor.migrate(after)
                ItemFile = executor.loader.project_state(after).apps.get_model("inventory", "ItemFile")
                moved = ItemFile.objects.get(pk=document.pk).file.name
                self.assertRegex(moved, r"^documents/[0-9a-f]{32}/manual\.pdf$")
                self.assertTrue(default_storage.exists(moved))
                self.assertFalse(default_storage.exists(old))
            finally:
                executor = MigrationExecutor(connection)
                executor.migrate(executor.loader.graph.leaf_nodes())


@override_settings(**SETTINGS)
class LevelTests(MediaMixin, UniqueItemFixture, TestCase):
    """Photos and files belong to the item in general or to one unique item, chosen on either form."""

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def setUp(self):
        super().setUp()
        self.client.force_login(self.member)
        self.manual = ItemFile.objects.create(item=self.extinguisher, description="Manual",
                                              file=ContentFile(b"%PDF-1.4", name="manual.pdf"))
        self.dent = ItemImage.objects.create(item=self.extinguisher, unique_item=self.unique_item,
                                             image=png("blue"), description="Dent")

    def item_data(self, **extra):
        return {"name": "Fire extinguisher", "description": "", "barcode_data": "", "usage_level": "",
                "itemimage_set-TOTAL_FORMS": "0", "itemimage_set-INITIAL_FORMS": "0",
                "itemfile_set-TOTAL_FORMS": "0", "itemfile_set-INITIAL_FORMS": "0", **extra}

    def unique_data(self, **extra):
        return {"location": self.location.pk, "images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0",
                "files-TOTAL_FORMS": "0", "files-INITIAL_FORMS": "0", **extra}

    def test_create_forms_start_with_one_photo(self):
        response = self.client.get(reverse("create_item"))
        self.assertEqual(len(response.context["inlines"][0].forms), 1)
        response = self.client.get(reverse("update_item", args=[self.item.pk]))
        self.assertEqual(len(response.context["inlines"][0].forms), 1)  # the gallery adds more
        # Photos and files next to each other, then the stock.
        self.assertEqual([inline.prefix for inline in response.context["inlines"]],
                         ["itemimage_set", "itemfile_set", "itemlocation_set"])
        self.assertEqual(len(self.client.get(reverse("create_unique_item")).context["inlines"][0].forms), 1)

    def test_item_form_assigns_to_a_unique_item(self):
        url = reverse("update_item", args=[self.extinguisher.pk])
        response = self.client.get(url)
        field = response.context["inlines"][1].forms[0].fields["unique_item"]
        self.assertEqual(field.empty_label, "The item in general")
        self.assertIn("K7R-4XD @ Workshop · WS", [label for _value, label in field.choices])
        data = self.item_data(**{
            "itemfile_set-TOTAL_FORMS": "2", "itemfile_set-INITIAL_FORMS": "1",
            "itemfile_set-0-id": self.manual.pk, "itemfile_set-0-description": "Manual", "itemfile_set-0-unique_item": "",
            "itemfile_set-1-description": "Invoice", "itemfile_set-1-internal": "on",
            "itemfile_set-1-unique_item": self.unique_item.pk,
            "itemfile_set-1-file": SimpleUploadedFile("invoice.pdf", b"%PDF-1.4", content_type="application/pdf"),
        })
        self.assertEqual(self.client.post(url, data).status_code, 302)
        invoice = ItemFile.objects.get(description="Invoice")
        self.assertEqual((invoice.item, invoice.unique_item), (self.extinguisher, self.unique_item))
        # The item page shows what is general; the unique item has its own first.
        self.assertNotContains(self.client.get(self.extinguisher.get_absolute_url()), "Invoice")
        self.assertNotIn("unique_item", self.client.get(reverse("update_item", args=[self.item.pk])).context["inlines"][1].forms[0].fields)

    def test_unique_item_page_shows_its_own_first_and_marks_general(self):
        ItemImage.objects.create(item=self.extinguisher, image=png("red"), description="Type photo")
        self.client.logout()
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        self.assertLess(content.index("Dent"), content.index("Type photo"))
        self.assertIn('<span class="unique-item-general">general</span> Type photo', content)
        self.assertInHTML(f'<li><a href="{self.manual.get_absolute_url()}">Manual</a> <span class="unique-item-general">general</span></li>', content)
        item_page = self.client.get(self.extinguisher.get_absolute_url()).content.decode()
        self.assertIn("Type photo", item_page)
        self.assertNotIn("Dent", item_page)

    def test_level_can_change_on_the_unique_item_form(self):
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        forms = self.client.get(url).context["inlines"]
        self.assertEqual([form["level"].value() for form in forms[0].forms], ["unique", "unique"])  # Dent, new row
        self.assertEqual([form["level"].value() for form in forms[1].forms], ["item", "unique"])  # Manual, new row
        data = self.unique_data(**{
            "images-TOTAL_FORMS": "1", "images-INITIAL_FORMS": "1",
            "images-0-id": self.dent.pk, "images-0-description": "Dent", "images-0-level": "item",
            "files-TOTAL_FORMS": "1", "files-INITIAL_FORMS": "1",
            "files-0-id": self.manual.pk, "files-0-description": "Manual", "files-0-level": "unique",
        })
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.dent.refresh_from_db()
        self.manual.refresh_from_db()
        self.assertEqual((self.dent.unique_item, self.manual.unique_item), (None, self.unique_item))

    def test_new_photo_on_either_level(self):
        url = reverse("update_unique_item", args=[self.unique_item.pk])
        data = self.unique_data(**{
            "images-TOTAL_FORMS": "3", "images-INITIAL_FORMS": "1",
            "images-0-id": self.dent.pk, "images-0-description": "Dent", "images-0-level": "unique",
            "images-1-image": png("green"), "images-1-description": "Label", "images-1-level": "item", "images-1-is_primary": "on",
            "images-2-image": png("yellow"), "images-2-description": "Serial plate", "images-2-level": "unique", "images-2-is_primary": "on",
        })
        self.assertEqual(self.client.post(url, data).status_code, 302)
        label, plate = ItemImage.objects.get(description="Label"), ItemImage.objects.get(description="Serial plate")
        self.assertEqual((label.unique_item, label.is_primary, plate.unique_item, plate.is_primary),
                         (None, True, self.unique_item, True))

    def test_unique_item_must_belong_to_the_item(self):
        other = UniqueItem.objects.create(item=self.extinguisher, location=self.location)
        image = ItemImage(item=self.item, unique_item=other, image="items/x.jpg")
        with self.assertRaises(ValidationError):
            image.full_clean()
        image.save()
        self.assertEqual(image.item, self.extinguisher)


@override_settings(**SETTINGS)
class GalleryFormTests(MediaMixin, UniqueItemFixture, TestCase):
    """The photo and file rows behind the gallery and its modal (media_gallery.js)."""

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()
        cls.editor = get_user_model().objects.create_user(username="editor")
        cls.editor.groups.add(local_group())
        grant(cls.editor, "delete_itemimage", "delete_itemfile")

    def setUp(self):
        super().setUp()
        self.photo = ItemImage.objects.create(item=self.extinguisher, image=png("red"), description="Front",
                                              ocr_text="ABC", ocr_timestamp=timezone.now())
        self.manual = ItemFile.objects.create(item=self.extinguisher, description="Manual",
                                              file=ContentFile(b"%PDF-1.4", name="manual.pdf"))
        self.url = reverse("update_item", args=[self.extinguisher.pk])

    def data(self, photo=None, file=None):
        data = {"name": "Fire extinguisher", "description": "", "barcode_data": "", "usage_level": "",
                "itemimage_set-TOTAL_FORMS": "1", "itemimage_set-INITIAL_FORMS": "1",
                "itemimage_set-0-id": self.photo.pk, "itemimage_set-0-description": "Front", "itemimage_set-0-unique_item": "",
                "itemfile_set-TOTAL_FORMS": "1", "itemfile_set-INITIAL_FORMS": "1",
                "itemfile_set-0-id": self.manual.pk, "itemfile_set-0-description": "Manual", "itemfile_set-0-unique_item": ""}
        data.update({f"itemimage_set-0-{key}": value for key, value in (photo or {}).items()})
        data.update({f"itemfile_set-0-{key}": value for key, value in (file or {}).items()})
        return data

    def test_rows_carry_what_the_gallery_shows(self):
        self.client.force_login(self.editor)
        content = self.client.get(self.url).content.decode()
        self.assertIn('data-formset="itemimage_set"', content)
        self.assertIn('data-media="photo"', content)
        self.assertIn('data-media="file"', content)
        self.assertIn("data-can-delete", content)
        self.assertRegex(content, r'data-media-info data-kind="photo" data-saved\s+data-name="Front" data-image="/media/items/')
        self.assertRegex(content, r'data-thumb="/media/cache/')
        self.assertIn(f'data-name="Manual" data-href="{self.manual.get_absolute_url()}"', content)
        self.assertIn('id="media-modal"', content)
        for gone in ("camera_modal", "placeholder.svg", "Tap to take Photo"):
            self.assertNotIn(gone, content)

    def test_replacing_a_photo_removes_the_old_file(self):
        self.client.force_login(self.member)
        old = self.photo.image.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, self.data(photo={"image": png("blue")}))
        self.assertEqual(response.status_code, 302)
        self.photo.refresh_from_db()
        self.assertNotEqual(self.photo.image.name, old)
        self.assertFalse(default_storage.exists(old))
        self.assertIsNone(self.photo.ocr_text)  # recognized again later

    def test_deleting_needs_permission(self):
        self.client.force_login(self.member)
        content = self.client.get(self.url).content.decode()
        self.assertNotIn("data-can-delete", content)
        self.assertNotIn("itemimage_set-0-DELETE", content)
        self.client.post(self.url, self.data(photo={"DELETE": "on"}, file={"DELETE": "on"}))
        self.assertTrue(ItemImage.objects.filter(pk=self.photo.pk).exists())
        self.client.force_login(self.editor)
        name = self.photo.image.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, self.data(photo={"DELETE": "on"}, file={"DELETE": "on"}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ItemImage.objects.filter(pk=self.photo.pk).exists())
        self.assertFalse(ItemFile.objects.filter(pk=self.manual.pk).exists())
        self.assertFalse(default_storage.exists(name))


@override_settings(**SETTINGS)
class QuickActionTests(MediaMixin, UniqueItemFixture, TestCase):
    """Quick add of photos and files on detail pages, and moving a unique item."""

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()

    def setUp(self):
        super().setUp()
        self.client.force_login(self.member)

    def test_item_page_offers_quick_add_and_unique_item_plus(self):
        content = self.client.get(self.extinguisher.get_absolute_url()).content.decode()
        self.assertIn('data-quick-open="quick-photo-modal"', content)
        self.assertIn('data-quick-open="quick-file-modal"', content)
        self.assertIn(f'action="{reverse("quick_item_photo", args=[self.extinguisher.pk])}"', content)
        self.assertIn(f'href="{reverse("create_unique_item")}?item={self.extinguisher.pk}" data-bs-toggle="tooltip"', content)
        self.assertNotIn('btn-outline-primary" href="/item/unique/create', content)
        self.client.logout()
        content = self.client.get(self.extinguisher.get_absolute_url()).content.decode()
        self.assertNotIn("data-quick-open", content)
        self.assertNotIn("quick-photo-modal", content)

    def test_quick_photo_on_the_item_is_general_and_can_be_primary(self):
        old = ItemImage.objects.create(item=self.extinguisher, image=png("red"), is_primary=True)
        url = reverse("quick_item_photo", args=[self.extinguisher.pk])
        response = self.client.post(url, {"image": png("blue"), "description": "Side", "is_primary": "on"})
        self.assertRedirects(response, self.extinguisher.get_absolute_url(), fetch_redirect_response=False)
        new = ItemImage.objects.get(description="Side")
        old.refresh_from_db()
        self.assertEqual((new.unique_item, new.is_primary, old.is_primary), (None, True, False))

    def test_quick_add_on_the_unique_item_belongs_to_it(self):
        response = self.client.post(reverse("quick_unique_item_file", args=[self.unique_item.pk]), {
            "file": SimpleUploadedFile("invoice.pdf", b"%PDF-1.4"), "description": "Invoice", "internal": "on"})
        self.assertRedirects(response, self.unique_item.get_absolute_url(), fetch_redirect_response=False)
        invoice = ItemFile.objects.get(description="Invoice")
        self.assertEqual((invoice.item, invoice.unique_item, invoice.internal), (self.extinguisher, self.unique_item, True))
        self.client.post(reverse("quick_unique_item_photo", args=[self.unique_item.pk]), {"image": png("green")})
        self.assertEqual(self.unique_item.images.count(), 1)

    def test_quick_add_needs_a_file_and_permission(self):
        response = self.client.post(reverse("quick_item_file", args=[self.extinguisher.pk]), {"description": "Nothing"}, follow=True)
        self.assertContains(response, "This field is required.")
        self.assertFalse(ItemFile.objects.exists())
        outsider = get_user_model().objects.create_user(username="outsider")
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(reverse("quick_item_photo", args=[self.extinguisher.pk]), {"image": png()}).status_code, 403)

    def test_unique_item_page_actions(self):
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        self.assertIn("data-move-open", content)
        self.assertIn(f'action="{reverse("move_unique_item", args=[self.unique_item.pk])}"', content)
        self.assertNotIn("Edit or move", content)
        self.assertNotIn(reverse("dispose_unique_item", args=[self.unique_item.pk]), content)  # members cannot dispose
        self.client.force_login(self.insider)
        content = self.client.get(self.unique_item.get_absolute_url()).content.decode()
        self.assertInHTML(f'<a class="btn btn-danger item-icon-action" href="{reverse("dispose_unique_item", args=[self.unique_item.pk])}" '
                          f'>{icon("archive")} <span class="action-label">Remove from inventory</span></a>', content)

    def test_move(self):
        url = reverse("move_unique_item", args=[self.unique_item.pk])
        response = self.client.post(url, {"location": self.shelf.pk})
        self.assertRedirects(response, self.unique_item.get_absolute_url(), fetch_redirect_response=False)
        self.unique_item.refresh_from_db()
        self.assertEqual(self.unique_item.location, self.shelf)
        moved = self.unique_item.change_log.get(action="moved")
        self.assertEqual((moved.actor, moved.other_location, moved.location), (self.member, self.location, self.shelf))
        self.client.post(url, {"location": ""})
        self.unique_item.refresh_from_db()
        self.assertEqual(self.unique_item.location, self.shelf)
        self.client.force_login(get_user_model().objects.create_user(username="outsider"))
        self.assertEqual(self.client.post(url, {"location": self.location.pk}).status_code, 403)

    def test_location_lookup_for_scans(self):
        url = reverse("location_lookup")
        self.assertEqual(self.client.get(url, {"q": "WS"}).json(),
                         {"id": self.location.pk, "text": "Workshop · WS",
                          "html": '<span class="loc-label"><span class="loc-title">Workshop</span> '
                                  '<span class="loc-code">WS</span></span>'})
        self.assertEqual(self.client.get(url, {"q": f"https://inv.zam.haus{self.shelf.get_absolute_url()}"}).json()["id"], self.shelf.pk)
        label = services.claim(make_id("ABCDE").code, self.shelf, None)
        self.assertEqual(self.client.get(url, {"q": f"HTTPS://I.ZAM.HAUS/{label.code}"}).json()["id"], self.shelf.pk)
        self.assertEqual(self.client.get(url, {"q": "nowhere"}).status_code, 404)

    def test_location_search_finds_pasted_label_urls_and_ids(self):
        # A scanner typing into the search field, or a pasted link, finds the location.
        self.client.force_login(self.insider)
        label = services.claim(make_id("ABCDE").code, self.shelf, None)
        for url in ("location-autocomplete", "parent_location_autocomplete"):
            for query in (f"https://inv.zam.haus{self.shelf.get_absolute_url()}", f"HTTPS://I.ZAM.HAUS/{label.code}", label.code):
                with self.subTest(url=url, query=query):
                    results = self.client.get(reverse(url), {"q": query}).json()["results"]
                    self.assertEqual([result["id"] for result in results], [str(self.shelf.pk)])

    def test_location_fields_offer_a_scan_button(self):
        from ..forms import MoveUniqueItemForm, ItemLocationForm
        html = str(MoveUniqueItemForm(instance=self.unique_item)["location"])
        self.assertIn('class="input-group location-scan-group"', html)
        self.assertIn(f'data-location-scan disabled aria-label="Scan location label" data-lookup-url="{reverse("location_lookup")}"', html)
        self.assertIn("inventory/location_scan.js", str(MoveUniqueItemForm().media))
        # A fixed location (adding stock at a given location) cannot be changed, so no button.
        fixed = ItemLocationForm(initial={"location": self.location.pk})
        self.assertNotIn("data-location-scan", str(fixed["location"]))


@override_settings(**SETTINGS)
class UsageLevelDisplayTests(UniqueItemFixture, TestCase):
    """The briefing requirement: a symbol in a coloured circle, explained on hover or written out."""

    @classmethod
    def setUpTestData(cls):
        cls.create_unique_items()  # the extinguisher is green

    def test_detail_pages_show_the_long_form(self):
        long_form = ('<span class="usage-level usage-level-green"><span class="usage-level-symbol" aria-hidden="true">' + icon("check-lg") + '</span>'
                     'Green: free to use, no briefing required</span>')
        for url in (self.extinguisher.get_absolute_url(), self.unique_item.get_absolute_url()):
            self.assertInHTML(long_form, self.client.get(url).content.decode(), count=1)

    def test_location_page_shows_the_short_form_with_hover_text(self):
        self.unique_item.usage_level = "red"
        self.unique_item.save()
        self.assertInHTML(
            '<span class="usage-level usage-level-red" data-bs-toggle="tooltip" title="Red: use only after a briefing">'
            '<span class="usage-level-symbol" aria-hidden="true">' + icon("x-lg") + '</span>red'
            '<span class="visually-hidden">: Red: use only after a briefing</span></span>',
            self.client.get(self.location.get_absolute_url()).content.decode())

    def test_forms_offer_the_explanations(self):
        self.client.force_login(self.member)
        choices = dict(self.client.get(reverse("update_unique_item", args=[self.unique_item.pk])).context["form"].fields["usage_level"].choices)
        self.assertEqual(choices, {"": "As set for the item", "green": "Green: free to use, no briefing required",
                                   "yellow": "Yellow: use with care, ask if in doubt", "red": "Red: use only after a briefing"})
        choices = dict(self.client.get(reverse("update_item", args=[self.extinguisher.pk])).context["form"].fields["usage_level"].choices)
        self.assertEqual(choices[""], "Not specified")

    def test_unique_item_list_shows_only_differing_levels(self):
        UniqueItem.objects.create(item=self.extinguisher, location=self.location, usage_level="green")
        UniqueItem.objects.create(item=self.extinguisher, location=self.location, usage_level="red")
        response = self.client.get(self.extinguisher.get_absolute_url())
        content = response.content.decode()
        # Only the red one contradicts the item's green; same or empty is not repeated.
        self.assertEqual(content.count('class="unique-item-differs"'), 1)
        self.assertIn("usage-level-red", content)

    def test_nothing_shown_when_not_set(self):
        self.extinguisher.usage_level = ""
        self.extinguisher.save()
        for url in (self.extinguisher.get_absolute_url(), self.unique_item.get_absolute_url(), self.location.get_absolute_url()):
            content = self.client.get(url).content.decode()
            self.assertNotIn('class="usage-level', content, url)
            self.assertNotIn("Usage level</dt>", content, url)
            self.assertNotIn("No usage level", content, url)
