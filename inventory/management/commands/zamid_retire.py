from django.core.management.base import BaseCommand, CommandError

from inventory.zamid import core, parsing, services


class Command(BaseCommand):
    help = "Retire a ZAM ID. It keeps its target and is never reused."

    def add_arguments(self, parser):
        parser.add_argument("code")
        parser.add_argument("--note", default="")

    def handle(self, *args, code, note, **options):
        try:
            zid = services.retire(parsing.code_from_scan(code), None, note)
        except core.InvalidZamId as e:
            raise CommandError(f"{code}: invalid ID ({e.args[0]})")
        except services.ZamIdError as e:
            raise CommandError(str(e))
        self.stdout.write(f"{zid.display} retired")
