from django.core.management.base import BaseCommand

from zamid import core, parsing
from zamid.models import ZamId


class Command(BaseCommand):
    help = "Show the normalized form, validity, status and suggestions for typed or scanned IDs."

    def add_arguments(self, parser):
        parser.add_argument("inputs", nargs="+")

    def handle(self, *args, inputs, **options):
        for raw in inputs:
            try:
                code = parsing.code_from_scan(raw)
            except core.InvalidZamId as e:
                line = f"{raw}: invalid ({e.args[0]})"
                if e.args[0] == "checksum":
                    known = ZamId.objects.filter(pk__in=parsing.suggestions_for_scan(raw)).values_list("code", flat=True)
                    if known:
                        line += "; did you mean " + ", ".join(core.display(c) for c in sorted(known))
                self.stdout.write(line)
                continue
            zid = ZamId.objects.select_related("item", "location").filter(pk=code).first()
            if zid is None:
                self.stdout.write(f"{raw}: {core.display(code)} valid, not issued")
                continue
            target = zid.target
            self.stdout.write(f"{raw}: {zid.display} {zid.status}"
                              + (f" -> {zid.target_field} {target}" if target is not None else ""))
