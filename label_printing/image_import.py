"""Importing label images in bulk (admin → Label images → Import): images, or ZIP archives of them such as a
set of safety signs (ISO 7010) or tool icons. Each becomes a label image named after its file."""
import zipfile
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext as _

from .models import LabelImage

SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 1000


def files(upload):
    """(file name, bytes) of an uploaded image, or of the images in an uploaded ZIP archive."""
    if not upload.name.lower().endswith(".zip"):
        yield upload.name, upload.read()
        return
    with zipfile.ZipFile(upload) as archive:
        for info in archive.infolist()[:MAX_FILES]:
            path = PurePosixPath(info.filename)
            if info.is_dir() or path.name.startswith(".") or "__MACOSX" in path.parts:
                continue
            if path.suffix.lower() in SUFFIXES and info.file_size <= MAX_FILE_BYTES:
                yield path.name, archive.read(info)


def unique_name(stem):
    name, number = stem[:64], 2
    while LabelImage.objects.filter(name=name).exists():
        suffix = f" {number}"
        name, number = stem[:64 - len(suffix)] + suffix, number + 1
    return name


def import_images(uploads):
    """(label images created, [(file name, why not)])."""
    created, skipped = [], []
    for upload in uploads:
        try:
            found = list(files(upload))
        except zipfile.BadZipFile:
            skipped.append((upload.name, _("not a ZIP archive")))
            continue
        for filename, data in found:
            if PurePosixPath(filename).suffix.lower() not in SUFFIXES:
                skipped.append((filename, _("not a PNG, GIF, JPEG or WebP image")))
                continue
            image = LabelImage(name=unique_name(PurePosixPath(filename).stem))
            image.image.save(filename, ContentFile(data), save=False)
            try:
                image.full_clean()
                image.save()
            except (ValidationError, OSError, ValueError) as error:
                image.image.delete(save=False)
                skipped.append((filename, " ".join(getattr(error, "messages", [str(error)]))))
                continue
            created.append(image)
    return created, skipped
