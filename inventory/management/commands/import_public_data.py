import json
import tarfile
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from inventory import public_export
from inventory.models import Item, Location


class Command(BaseCommand):
    help = "Load an export of export_public_data (archive or directory) into an empty, migrated database."

    def add_arguments(self, parser):
        parser.add_argument("source")

    def handle(self, *args, source, **options):
        source = Path(source)
        if not source.exists():
            raise CommandError(f"{source} does not exist.")
        if Item._base_manager.exists() or Location._base_manager.exists():
            raise CommandError("The database already holds an inventory. Start from an empty one: remove "
                               "db.sqlite3 (or create a new database), run migrate, then import again.")
        with tempfile.TemporaryDirectory() as tmp:
            if source.is_dir():
                directory = source
            else:
                directory = Path(tmp)
                with tarfile.open(source) as tar:
                    for name in ("data.json", "export-info.json"):
                        tar.extract(name, directory, filter="data")
            info = json.loads((directory / "export-info.json").read_text())
            if info["format"] != public_export.FORMAT_VERSION:
                raise CommandError(f"Unsupported export format {info['format']}.")
            problem = public_export.migration_problem(info["migrations"])
            if problem:
                raise CommandError(problem)
            call_command("loaddata", directory / "data.json", ignorenonexistent=True,
                         verbosity=options["verbosity"])
        self.stdout.write("Photos and documents are not part of the export: with MEDIA_REMOTE_URL, pages load them "
                          "when shown, or all at once with: ./manage.py download_public_media")
        self.stdout.write("User accounts are not part of the export; create one with: ./manage.py createsuperuser")
