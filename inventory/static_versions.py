"""
Static file URLs carry a version (?v=<content hash>), so browsers load a changed file at
once instead of a cached copy: Safari kept serving an old stylesheet for a long time while
the pages were already new. The hash is recomputed only when a file changes.
"""
import hashlib
import os
from functools import lru_cache

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


@lru_cache(maxsize=2048)
def _digest(path, mtime_ns, size):
    with open(path, "rb") as file:
        return hashlib.md5(file.read(), usedforsecurity=False).hexdigest()[:10]


class VersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        if not name or "?" in name or "#" in name:
            return url
        # The source files first: in development they are what is served, and STATIC_ROOT may
        # hold an outdated copy; in production collectstatic made both the same.
        path = finders.find(name) or (self.path(name) if self.exists(name) else None)
        if not path:
            return url
        stat = os.stat(path)
        return f"{url}?v={_digest(path, stat.st_mtime_ns, stat.st_size)}"
