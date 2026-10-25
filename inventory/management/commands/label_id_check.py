from django.core.management.base import BaseCommand, CommandError

from inventory.label_ids import core, parsing
from inventory.label_ids.lookup import annotate_label_code
from inventory.label_ids.targets import RELATED_TARGETS
from inventory.codes import reads_as_label_id
from inventory.models import LabelId, Location, LocationFormerCode, UniqueItem


class Command(BaseCommand):
    help = ("Show the normalized form, validity, status and suggestions for typed or scanned IDs; "
            "with --missing, list unique items in the inventory that have no active ID; "
            "with --collisions, list location codes that read as issued IDs.")

    def add_arguments(self, parser):
        parser.add_argument("inputs", nargs="*")
        parser.add_argument("--missing", action="store_true",
                            help="List unique items in the inventory without an active ID (e.g. after it was retired).")
        parser.add_argument("--collisions", action="store_true",
                            help="List location codes and former codes that read as issued IDs (codes win when "
                                 "scanned or typed, so such an ID cannot be reached by its code).")

    def handle(self, *args, inputs, missing, collisions, **options):
        if not inputs and not missing and not collisions:
            raise CommandError("Give IDs to check, or --missing or --collisions.")
        if collisions:
            codes = [(code, f"location #{pk}") for pk, code in Location.objects.values_list("pk", "unique_identifier")]
            codes += [(code, "former code") for code in LocationFormerCode.objects.values_list("code", flat=True)]
            found = 0
            for code, kind in codes:
                if (lid := reads_as_label_id(code)) is not None:
                    found += 1
                    self.stdout.write(f"{code} ({kind}) reads as the ID {lid.display}")
            self.stdout.write(f"{found} collisions")
        if missing:
            unique_items = annotate_label_code(UniqueItem.active.select_related("item", "location")).filter(label_code__isnull=True)
            for unique_item in unique_items:
                self.stdout.write(f"unique item #{unique_item.pk} {unique_item.item} @ {unique_item.location}: no active ID")
        for raw in inputs:
            try:
                code = parsing.code_from_scan(raw)
            except core.InvalidLabelId as e:
                line = f"{raw}: invalid ({e.args[0]})"
                if e.args[0] == "checksum":
                    known = LabelId.objects.filter(pk__in=parsing.suggestions_for_scan(raw)).values_list("code", flat=True)
                    if known:
                        line += "; did you mean " + ", ".join(core.display(c) for c in sorted(known))
                self.stdout.write(line)
                continue
            lid = LabelId.objects.select_related(*RELATED_TARGETS).filter(pk=code).first()
            if lid is None:
                self.stdout.write(f"{raw}: {core.display(code)} valid, not issued")
                continue
            target = lid.target
            self.stdout.write(f"{raw}: {lid.display} {lid.status}"
                              + (f" -> {lid.target_field} {target}" if target is not None else ""))
