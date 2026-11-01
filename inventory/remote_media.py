"""Media files, and in development those of another installation.

With MEDIA_REMOTE_URL set and DEBUG on (a development system with an imported public export,
docs/data-export.md), a file missing in MEDIA_ROOT is loaded from that installation when something asks for it,
and kept: photos, public documents and thumbnails. Files here come first. Only what the installation serves to
visitors who are not logged in comes through; redirects (e.g. to the login) are not followed.
"""
import hashlib
import logging
import os
import tempfile
import urllib.error
import urllib.request
from urllib.parse import quote, urljoin

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from sorl.thumbnail.kvstores.cached_db_kvstore import KVStore

logger = logging.getLogger(__name__)

TIMEOUT = 10  # seconds
MISSING_FOR = 600  # seconds a file the installation did not have is not asked for again


def enabled():
    return bool(settings.DEBUG and settings.MEDIA_REMOTE_URL)


def remote_url(name):
    """Where the installation at MEDIA_REMOTE_URL serves the media file name, or None."""
    if name.startswith("documents/"):
        # nginx serves attached documents only through the app, which checks internal ones.
        from .models import ItemFile
        document = ItemFile.objects.filter(file=name, internal=False).first()
        if document is None:
            return None
        path = reverse("item_file", args=[document.pk])
    else:
        path = "/" + settings.MEDIA_URL.lstrip("/") + quote(name)
    return urljoin(settings.MEDIA_REMOTE_URL, path)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # the redirect becomes an HTTPError


_opener = urllib.request.build_opener(_NoRedirects)


def _open_url(url):
    """The body of url; HTTPError for any other answer than 2xx."""
    request = urllib.request.Request(url, headers={"User-Agent": "inventory-development-media"})
    with _opener.open(request, timeout=TIMEOUT) as response:
        return response.read()


class MediaStorage(FileSystemStorage):
    """MEDIA_ROOT; in development with MEDIA_REMOTE_URL, missing files come from that installation.

    The class is part of every thumbnail's file name (sorl-thumbnail hashes the storage of the source):
    renaming or moving it renames all thumbnails, which are then made anew.
    """

    def exists_here(self, name):
        return super().exists(name)

    def exists(self, name):
        return self.exists_here(name) or self.fetch(name)

    def _open(self, name, mode="rb"):
        if not self.exists_here(name):
            self.fetch(name)
        return super()._open(name, mode)

    def fetch(self, name, retry=False):
        """Load name from MEDIA_REMOTE_URL unless it is here; whether it is here now. A file the installation
        did not have is asked for again after MISSING_FOR seconds, or with retry."""
        if not enabled():
            return False
        if self.exists_here(name):
            return True
        missing_key = "remote-media-missing:" + hashlib.md5(name.encode()).hexdigest()
        if not retry and cache.get(missing_key):
            return False
        target = self.path(name)  # SuspiciousFileOperation for a name outside MEDIA_ROOT
        url = remote_url(name)
        try:
            data = _open_url(url) if url else None
        except urllib.error.HTTPError as e:
            if e.code != 404:
                logger.warning("Media file %s not loaded from %s: %s", name, url, e)
            data = None
        except OSError as e:  # unreachable, timeout
            logger.warning("Media file %s not loaded from %s: %s", name, url, e)
            data = None
        if data is None:
            cache.set(missing_key, True, MISSING_FOR)
            return False
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # Written next to the target and renamed, so that no half file is ever served.
        handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".remote-")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            os.chmod(temporary, self.file_permissions_mode or 0o644)
            os.replace(temporary, target)
        except BaseException:
            os.unlink(temporary)
            raise
        return True


def _here(image_file):
    storage = image_file.storage
    return getattr(storage, "exists_here", storage.exists)(image_file.name)


class ThumbnailKVStore(KVStore):
    """sorl-thumbnail's store, content with a thumbnail whose source is not here.

    sorl records a thumbnail together with its source and the size of the source, read from the source file.
    A thumbnail loaded from MEDIA_REMOTE_URL is recorded without its source, which stays there; in production
    this keeps a page working whose photo file got lost.
    """

    def get_or_set(self, image_file):
        if not _here(image_file):
            return image_file
        return super().get_or_set(image_file)

    def set(self, image_file, source=None):
        super().set(image_file, source if source is None or _here(source) else None)
