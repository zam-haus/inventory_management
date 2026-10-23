"""Building structure (docs/location-structure.md).

Location types get a category (space, storage unit, container), the building structure they
belong to, a description, the admin-only lock, number ranges per area and a type of
sub-locations. Locations get an axis, fire-load-free and outdoor flags and responsible teams;
number ranges belong to a room or area and one location type.

Data: moveable types are containers from now on. Sequences are digits or letters only: types with
a mixed sequence (hexadecimal boxes, alphanumeric pallets) count in digits; existing codes stay as
they are and creating new locations skips codes that are taken.
"""
import django.db.models.deletion
from django.db import migrations, models

NUMERIC = "0123456789"
KEPT_SEQUENCES = {NUMERIC, "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def forward(apps, schema_editor):
    LocationType = apps.get_model("inventory", "LocationType")
    LocationType.objects.filter(moveable=True).update(category="container")
    LocationType.objects.exclude(auto_sequence__isnull=True).exclude(auto_sequence="").exclude(
        auto_sequence__in=KEPT_SEQUENCES).update(auto_sequence=NUMERIC)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_team_code_color_parent"),
        ("inventory", "0035_location_purpose"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocationAxis",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "number",
                    models.PositiveSmallIntegerField(
                        help_text="Order from left to right.",
                        unique=True,
                        verbose_name="number",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="name")),
            ],
            options={
                "verbose_name": "axis",
                "verbose_name_plural": "axes",
                "ordering": ("number",),
            },
        ),
        migrations.AddField(
            model_name="location",
            name="fire_load_free",
            field=models.BooleanField(
                default=False,
                help_text="No combustible materials may be stored here. Applies to everything inside.",
                verbose_name="free of fire load",
            ),
        ),
        migrations.AddField(
            model_name="location",
            name="outdoor",
            field=models.BooleanField(default=False, verbose_name="outdoors"),
        ),
        migrations.AddField(
            model_name="location",
            name="responsible_teams",
            field=models.ManyToManyField(
                blank=True,
                related_name="locations",
                to="accounts.team",
                verbose_name="responsible teams",
            ),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="admin_only",
            field=models.BooleanField(
                default=False,
                help_text="Locations of this type are created, changed and deleted only in the admin, which requires staff status. On the inventory pages only their purpose can be changed; photo, place and deletion are locked, what they contain can still be moved.",
                verbose_name="admin only",
            ),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="area_numbering",
            field=models.BooleanField(
                default=False,
                help_text="New locations of this type get a free number from the number range of the room or area they are created in, on its page. Only for types with building-wide codes that are not moved, with a short name prefix and the numeric sequence.",
                verbose_name="number ranges per area",
            ),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("space", "Space"),
                    ("storage_unit", "Storage unit"),
                    ("container", "Container"),
                ],
                help_text="Space: levels, rooms and areas. Storage unit: furniture for storing things such as shelves, cabinets, workbenches with drawers and tool trolleys, with their compartments. Container: moves with its contents, such as boxes, cartons and pallets. Empty for anything else, e.g. on loan.",
                max_length=16,
                verbose_name="location category",
            ),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="description",
            field=models.TextField(blank=True, verbose_name="description"),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="structure",
            field=models.CharField(
                blank=True,
                choices=[
                    ("level", "Building and level"),
                    ("room", "Room"),
                    ("area", "Area"),
                ],
                help_text="Set for the fixed building structure: building and level, room or area. Empty for furniture and containers such as shelves and boxes.",
                max_length=8,
                verbose_name="building structure",
            ),
        ),
        migrations.AddField(
            model_name="locationtype",
            name="sublocation_type",
            field=models.ForeignKey(
                blank=True,
                help_text="Creating a location of this type on the inventory pages asks how many of these to add inside it, e.g. compartments of a shelf.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="inventory.locationtype",
                verbose_name="type of sub-locations",
            ),
        ),
        migrations.AlterField(
            model_name="locationtype",
            name="auto_sequence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("0123456789", "Numeric (0-9)"),
                    ("abcdefghijklmnopqrstuvwxyz", "Letters lowercase (a-z)"),
                    ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "Letters uppercase (A-Z)"),
                ],
                max_length=128,
                null=True,
                verbose_name="sequence",
            ),
        ),
        migrations.AddField(
            model_name="location",
            name="axis",
            field=models.ForeignKey(
                blank=True,
                help_text="Set on locations directly below a level; their parts inherit it.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="locations",
                to="inventory.locationaxis",
                verbose_name="axis",
            ),
        ),
        migrations.CreateModel(
            name="LocationNumberRange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("first", models.PositiveIntegerField(verbose_name="from")),
                ("last", models.PositiveIntegerField(verbose_name="to")),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="number_ranges",
                        to="inventory.location",
                        verbose_name="location",
                    ),
                ),
                (
                    "type",
                    models.ForeignKey(
                        limit_choices_to={"area_numbering": True},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="number_ranges",
                        to="inventory.locationtype",
                        verbose_name="location type",
                    ),
                ),
            ],
            options={
                "verbose_name": "number range",
                "verbose_name_plural": "number ranges",
                "ordering": ("first",),
            },
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
