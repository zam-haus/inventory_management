from collections import defaultdict

import django.db.models.functions.text
from django.db import migrations, models


def check_codes(apps, schema_editor):
    """Codes that differ only in capital and small letters must be renamed before (admin) – say which."""
    found = []
    for model, field in (("Location", "unique_identifier"), ("LocationFormerCode", "code")):
        by_upper = defaultdict(list)
        for code in apps.get_model("inventory", model).objects.values_list(field, flat=True):
            by_upper[code.upper()].append(code)
        found += [" = ".join(sorted(codes)) for codes in by_upper.values() if len(codes) > 1]
    if found:
        raise RuntimeError("Location codes differ only in capital and small letters; rename them first: "
                           + "; ".join(sorted(found)))


class Migration(migrations.Migration):
    """Location codes (and former codes) are unique ignoring case: labels hold them in capitals."""

    dependencies = [
        ("accounts", "0005_team_code_color_parent"),
        ("inventory", "0043_remove_zpl_template"),
    ]

    operations = [
        migrations.RunPython(check_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Upper("unique_identifier"),
                name="location_code_unique_ignoring_case",
            ),
        ),
        migrations.AddConstraint(
            model_name="locationformercode",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Upper("code"),
                name="former_code_unique_ignoring_case",
            ),
        ),
    ]
