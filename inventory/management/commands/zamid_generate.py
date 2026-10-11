from django.core.management.base import BaseCommand, CommandError

from inventory.zamid import services


class Command(BaseCommand):
    help = "Create new reserved ZAM IDs in one transaction."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, required=True)
        parser.add_argument("--batch", default="", help="label batch / print run name")

    def handle(self, *args, count, batch, **options):
        try:
            created = services.generate_batch(count, batch)
        except services.ZamIdError as e:
            raise CommandError(str(e))
        for zid in created:
            self.stdout.write(zid.display)
