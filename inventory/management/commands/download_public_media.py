from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from inventory import public_export, remote_media


class Command(BaseCommand):
    help = ("Load the photos and public documents of the imported inventory from MEDIA_REMOTE_URL into "
            "MEDIA_ROOT, keeping files that are here already. Without it, pages load them when shown.")

    def add_arguments(self, parser):
        parser.add_argument("--jobs", type=int, default=4,
                            help="Files loaded at the same time (default 4, to spare the installation).")

    def handle(self, *args, jobs, **options):
        if not remote_media.enabled():
            raise CommandError("Set MEDIA_REMOTE_URL (e.g. https://inventar.zam.haus/) and DEBUG = True "
                               "in local_settings.py.")
        try:
            names = public_export.media_names(public_export.export_rows())
        except public_export.UnreviewedData as e:
            raise CommandError("inventory/public_export.py needs a review:\n  " + "\n  ".join(e.args[0]))
        missing_here = [name for name in names if not default_storage.exists_here(name)]
        self.stdout.write(f"{len(names) - len(missing_here)} of {len(names)} files are here already; loading "
                          f"{len(missing_here)} from {settings.MEDIA_REMOTE_URL}.")
        not_there = []
        pool = ThreadPoolExecutor(jobs)
        try:
            loaded = pool.map(lambda name: default_storage.fetch(name, retry=True), missing_here)
            for count, (name, found) in enumerate(zip(missing_here, loaded), 1):
                if not found:
                    not_there.append(name)
                    self.stderr.write(f"not loaded: {name}")
                if count % 500 == 0:
                    self.stdout.write(f"{count} of {len(missing_here)}")
        finally:
            pool.shutdown(cancel_futures=True)  # on Ctrl-C, without loading the rest first
        self.stdout.write(f"Loaded {len(missing_here) - len(not_there)} files, {len(not_there)} not.")
