"""Teams get a code, a badge colour and a parent team (docs/location-structure.md)."""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_team_squashed_0004"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="code",
            field=models.CharField(
                blank=True,
                help_text="Short code shown as a badge, e.g. H for the wood workshop or ⌂ for the caretakers.",
                max_length=4,
                validators=[
                    django.core.validators.RegexValidator(
                        "^\\S*$", message="No spaces allowed."
                    )
                ],
                verbose_name="code",
            ),
        ),
        migrations.AddField(
            model_name="team",
            name="color",
            field=models.CharField(
                blank=True,
                help_text="Badge colour as #rrggbb. Without one, the badge uses the parent team's colour.",
                max_length=7,
                validators=[
                    django.core.validators.RegexValidator(
                        "^#[0-9a-fA-F]{6}$", message="Enter a colour like #7d3a2d."
                    )
                ],
                verbose_name="colour",
            ),
        ),
        migrations.AddField(
            model_name="team",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="subteams",
                to="accounts.team",
                verbose_name="parent team",
            ),
        ),
        migrations.AddConstraint(
            model_name="team",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="team_code_unique",
            ),
        ),
    ]
