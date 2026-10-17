from django.core.management.base import BaseCommand, CommandError

from inventory.label_ids import core, parsing, services


class Command(BaseCommand):
    help = "Retire a label ID. It keeps its target and is never reused."

    def add_arguments(self, parser):
        parser.add_argument("code")
        parser.add_argument("--note", default="")

    def handle(self, *args, code, note, **options):
        try:
            lid = services.retire(parsing.code_from_scan(code), None, note)
        except core.InvalidLabelId as e:
            raise CommandError(f"{code}: invalid ID ({e.args[0]})")
        except services.LabelIdError as e:
            raise CommandError(str(e))
        self.stdout.write(f"{lid.display} retired")
