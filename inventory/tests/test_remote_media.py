import io
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image
from sorl.thumbnail import get_thumbnail
from sorl.thumbnail.models import KVStore

from .. import remote_media
from ..label_ids.testing import SETTINGS, InventoryFixture
from ..models import ItemFile, ItemImage
from ..urls import media

REMOTE = "https://remote.example/"


def jpeg(size=(400, 300)):
    content = io.BytesIO()
    Image.new("RGB", size, "red").save(content, "JPEG")
    return content.getvalue()


class RemoteMixin:
    """An empty MEDIA_ROOT here, and a remote installation serving self.remote (URL → bytes)."""

    def setUp(self):
        super().setUp()
        self.media = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media)
        override = override_settings(MEDIA_ROOT=str(self.media), DEBUG=True, MEDIA_REMOTE_URL=REMOTE)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()  # the store of failed requests and sorl-thumbnail's
        self.addCleanup(cache.clear)
        self.remote, self.requested = {}, []
        patcher = mock.patch.object(remote_media, "_open_url", self.open_url)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_url(self, url):
        self.requested.append(url)
        if url not in self.remote:
            raise HTTPError(url, 404, "Not Found", {}, None)
        return self.remote[url]


class StorageTests(RemoteMixin, SimpleTestCase):
    def test_missing_file_is_loaded_and_kept(self):
        self.remote[REMOTE + "media/items/1/a%20b.jpg"] = b"photo"
        with default_storage.open("items/1/a b.jpg") as file:
            self.assertEqual(file.read(), b"photo")
        self.assertEqual((self.media / "items/1/a b.jpg").read_bytes(), b"photo")
        self.assertTrue(default_storage.exists("items/1/a b.jpg"))
        self.assertEqual(len(self.requested), 1)

    def test_files_here_come_first(self):
        (self.media / "items/1").mkdir(parents=True)
        (self.media / "items/1/a.jpg").write_bytes(b"here")
        self.remote[REMOTE + "media/items/1/a.jpg"] = b"remote"
        with default_storage.open("items/1/a.jpg") as file:
            self.assertEqual(file.read(), b"here")
        self.assertEqual(self.requested, [])

    def test_missing_remotely_is_not_asked_again(self):
        self.assertFalse(default_storage.exists("items/1/a.jpg"))
        with self.assertRaises(FileNotFoundError):
            default_storage.open("items/1/a.jpg")
        self.assertEqual(self.requested, [REMOTE + "media/items/1/a.jpg"])
        self.assertFalse(default_storage.fetch("items/1/a.jpg", retry=True))
        self.assertEqual(len(self.requested), 2)

    def test_errors_are_logged(self):
        with mock.patch.object(remote_media, "_open_url", side_effect=URLError("unreachable")), \
                self.assertLogs("inventory.remote_media", "WARNING"):
            self.assertFalse(default_storage.exists("items/1/a.jpg"))

    def test_only_in_development(self):
        for settings in ({"DEBUG": False}, {"MEDIA_REMOTE_URL": ""}):
            with self.subTest(settings), override_settings(**settings):
                self.assertFalse(default_storage.exists("items/1/a.jpg"))
        self.assertEqual(self.requested, [])

    def test_names_outside_media_root(self):
        with self.assertRaises(SuspiciousFileOperation):
            default_storage.exists("../secret")
        self.assertEqual(self.requested, [])

    def test_media_view(self):
        self.remote[REMOTE + "media/items/1/a.jpg"] = b"photo"
        response = media(RequestFactory().get("/media/items/1/a.jpg"), "items/1/a.jpg")
        self.assertEqual(b"".join(response.streaming_content), b"photo")
        with self.assertRaises(PermissionDenied):
            media(RequestFactory().get("/media/documents/x/a.pdf"), "documents/x/a.pdf")


class RedirectTests(SimpleTestCase):
    """The real request: a redirect (e.g. to the login) is never taken for the file."""

    def test_redirects_are_not_followed(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/media/a.jpg":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"photo")
                else:
                    self.send_response(302)
                    self.send_header("Location", "/media/a.jpg")
                    self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        self.assertEqual(remote_media._open_url(base + "/media/a.jpg"), b"photo")
        with self.assertRaises(HTTPError) as raised:
            remote_media._open_url(base + "/login")
        self.assertEqual(raised.exception.code, 302)


class ThumbnailTests(RemoteMixin, TestCase):
    def remote_installation(self):
        """A photo and its thumbnail, made on the 'remote installation', which serves them."""
        remote_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, remote_root)
        (remote_root / "items/1").mkdir(parents=True)
        (remote_root / "items/1/a.jpg").write_bytes(jpeg())
        with override_settings(MEDIA_ROOT=str(remote_root), DEBUG=False):
            thumbnail = get_thumbnail("items/1/a.jpg", "160x160")
        for path in remote_root.rglob("*"):
            if path.is_file():
                self.remote[REMOTE + "media/" + str(path.relative_to(remote_root))] = path.read_bytes()
        cache.clear()
        KVStore.objects.all().delete()
        return thumbnail

    def test_thumbnail_comes_from_remote(self):
        remote = self.remote_installation()
        thumbnail = get_thumbnail("items/1/a.jpg", "160x160")
        self.assertEqual((thumbnail.name, thumbnail.size), (remote.name, [160, 120]))
        self.assertEqual(self.requested, [REMOTE + "media/" + remote.name])  # not the original
        self.assertTrue((self.media / remote.name).is_file())
        self.assertFalse((self.media / "items/1/a.jpg").exists())
        # Recorded: shown again without asking.
        self.assertEqual(get_thumbnail("items/1/a.jpg", "160x160").size, [160, 120])
        self.assertEqual(len(self.requested), 1)

    def test_thumbnail_is_made_here_when_remote_has_none(self):
        remote = self.remote_installation()
        del self.remote[REMOTE + "media/" + remote.name]
        thumbnail = get_thumbnail("items/1/a.jpg", "160x160")
        self.assertEqual((thumbnail.name, thumbnail.size), (remote.name, [160, 120]))
        self.assertEqual(self.requested, [REMOTE + "media/" + remote.name, REMOTE + "media/items/1/a.jpg"])
        self.assertTrue((self.media / remote.name).is_file())
        self.assertTrue((self.media / "items/1/a.jpg").is_file())

    @override_settings(DEBUG=False)
    def test_thumbnail_without_its_source(self):
        """Also in production: a photo file that got lost does not break the page showing its thumbnail."""
        (self.media / "items/1").mkdir(parents=True)
        (self.media / "items/1/a.jpg").write_bytes(jpeg())
        made = get_thumbnail("items/1/a.jpg", "160x160")
        (self.media / "items/1/a.jpg").unlink()
        cache.clear()
        KVStore.objects.all().delete()
        self.assertEqual(get_thumbnail("items/1/a.jpg", "160x160").size, made.size)


@override_settings(**SETTINGS)
class DocumentAndDownloadTests(RemoteMixin, InventoryFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_inventory()

    def test_document_comes_through_the_document_view(self):
        manual = ItemFile.objects.create(item=self.item, description="Manual",
                                         file=ContentFile(b"%PDF-1.4 manual", name="manual.pdf"))
        internal = ItemFile.objects.create(item=self.item, description="Invoice", internal=True,
                                           file=ContentFile(b"%PDF-1.4 invoice", name="invoice.pdf"))
        shutil.rmtree(self.media / "documents")
        cache.clear()  # saving asked the remote whether the names were taken
        self.remote[REMOTE + f"item/file/{manual.pk}"] = b"%PDF-1.4 manual"
        response = self.client.get(reverse("item_file", args=[manual.pk]))
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 manual")
        self.assertFalse(default_storage.exists(internal.file.name))
        self.assertEqual(self.requested, [REMOTE + f"item/file/{manual.pk}"])

    def download(self):
        stdout, stderr = StringIO(), StringIO()
        call_command("download_public_media", stdout=stdout, stderr=stderr)
        return stdout.getvalue(), stderr.getvalue()

    def test_download(self):
        for name in ("a", "b", "c"):
            ItemImage.objects.create(item=self.item, image=f"items/1/{name}.jpg")
        (self.media / "items/1").mkdir(parents=True)
        (self.media / "items/1/a.jpg").write_bytes(b"here")
        self.remote[REMOTE + "media/items/1/b.jpg"] = b"remote"
        stdout, stderr = self.download()
        self.assertIn("1 of 3 files are here already", stdout)
        self.assertIn("Loaded 1 files, 1 not.", stdout)
        self.assertEqual(stderr, "not loaded: items/1/c.jpg\n")
        self.assertEqual((self.media / "items/1/b.jpg").read_bytes(), b"remote")
        self.assertEqual(sorted(self.requested), [REMOTE + "media/items/1/b.jpg", REMOTE + "media/items/1/c.jpg"])
        # Again, files missing remotely are asked for again.
        self.remote[REMOTE + "media/items/1/c.jpg"] = b"remote"
        stdout, stderr = self.download()
        self.assertIn("Loaded 1 files, 0 not.", stdout)

    def test_download_needs_the_setting(self):
        with override_settings(MEDIA_REMOTE_URL=""), self.assertRaisesMessage(CommandError, "MEDIA_REMOTE_URL"):
            self.download()
