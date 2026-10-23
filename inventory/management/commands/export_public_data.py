from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inventory import public_export


class Command(BaseCommand):
    help = ("Export the inventory without personal data, for development databases (import_public_data); "
            "safe to publish after the review in docs/data-export.md. TARGET ending in .tar is written as "
            "an archive, otherwise as a new directory.")

    def add_arguments(self, parser):
        parser.add_argument("target")
        parser.add_argument("--no-media", action="store_true",
                            help="Leave out photos and documents (data only, a few MB).")

    def handle(self, *args, target, no_media, **options):
        try:
            rows = public_export.export_rows()
        except public_export.UnreviewedData as e:
            raise CommandError("Export stopped, inventory/public_export.py needs a review:\n  "
                               + "\n  ".join(e.args[0]))
        try:
            missing = public_export.write_export(target, rows, None if no_media else settings.MEDIA_ROOT)
        except FileExistsError:
            raise CommandError(f"{target} exists already.")
        for name in missing:
            self.stderr.write(f"media file missing, not exported: {name}")
        found = public_export.possible_personal_data(rows)
        for model, pk, field, match in found:
            self.stderr.write(self.style.WARNING(f"check {model} {pk} {field}: contains {match!r}"))
        self.stdout.write(f"Exported {len(rows)} objects to {target}.")
        if found:
            self.stdout.write(self.style.WARNING(
                f"{len(found)} kept texts contain a user's name or address; review them before publishing."))
