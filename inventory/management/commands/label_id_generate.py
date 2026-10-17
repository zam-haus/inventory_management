from django.core.management.base import BaseCommand, CommandError

from inventory.label_ids import services


class Command(BaseCommand):
    help = "Create new reserved label IDs in one transaction."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, required=True)
        parser.add_argument("--batch", default="", help="label batch / print run name")

    def handle(self, *args, count, batch, **options):
        try:
            created = services.generate_batch(count, batch)
        except services.LabelIdError as e:
            raise CommandError(str(e))
        for lid in created:
            self.stdout.write(lid.display)
