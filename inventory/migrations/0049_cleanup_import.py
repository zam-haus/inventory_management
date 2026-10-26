"""
Cleanup imports (inventory/cleanup, docs/item-cleanup.md) and the naming of categories, with the naming of the
categories of the default tree (0048_category_tree) that have one so far: derived from how their items are named.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


# How the items of these categories of the default tree are named (Category.naming), by full name.
NAMING = {
    "Arbeitsschutz & Sicherheit/Persönliche Schutzausrüstung":
        "<Art>[ Größe <Größe>]: Schnittschutzhandschuhe Größe 9",
    "Befestigungstechnik/Holzschrauben":
        "<Schraubenart> <Durchmesser>x<Länge>[ <Antrieb>][ Edelstahl][ Rundkopf]: Spanplattenschraube 4,5x40 TX20 Edelstahl",
    "Befestigungstechnik/Metrische Schrauben/DIN 7985 Linsenschrauben, Kreuzschlitz":
        "DIN 7985 M<Gewinde>x<Länge> <Antrieb> Linsenschraube[ <Oberfläche>]: DIN 7985 M6x70 PH3 Linsenschraube",
    "Befestigungstechnik/Metrische Schrauben/DIN 933 Sechskantschrauben, Vollgewinde":
        "DIN 933 M<Gewinde>x<Länge> <Antrieb> <Festigkeitsklasse>: DIN 933 M12x25 SW19 8.8",
    "Befestigungstechnik/Nägel & Drahtstifte":
        "<Art> <Durchmesser> x <Länge>mm[ <Oberfläche>]: Drahtstifte 2,5 x 60mm feuerverzinkt",
    "Beschläge/Möbelbeschläge/Gleiter & Möbelfüße":
        "<Art> [<Material>] [mit Schraube] <Durchmesser>mm[ <Farbe>]: Möbelgleiter Edelstahl 30mm",
    "Beschläge/Möbelbeschläge/Rohrkappen & Stopfen":
        "<Art> für <Rohrform> [<Farbe>] <Maße>[x<Wandstärke>]mm: Rohrkappe für Rechteckrohr schwarz 50x30x1.5-2mm",
    "Möbel, Haus & Garten/Lüftung":
        "<Art>[ <Form/Material>][ <Farbe>] <Maße>: Lüftungsgitter Plastik Mahagoni 290x125mm",
    "Oberfläche & Chemie/Holzpflege & Reparatur":
        "<Hartwachs|Weichwachs|Knetholz> <Farbton>[ RAL <Nr.>]: Weichwachs Kirschbaum rötlich",
    "Oberfläche & Chemie/Lacke, Farben & Holzschutz":
        "<Produkt>[ <Glanzgrad>][ <Farbe>][ RAL <Nr.>][ <Inhalt>]: Sprühlack Hochglanz Rapsgelb RAL 1021",
    "Oberfläche & Chemie/Schleifmittel/Schleifblätter & -streifen":
        "<Art>[ K<Körnung>][ <Maße>]: Schleifpapier K120 93x180mm",
    "Oberfläche & Chemie/Schleifmittel/Schleifbänder, Vlies & Polieren":
        "<Art>[ <Typ/Maße>][ K<Körnung>]: Schleifband K80",
    "Oberfläche & Chemie/Schleifmittel/Schleifscheiben & Fiberscheiben":
        "<Art> <Durchmesser>mm[ K<Körnung>][ <Zusatz>]: Schleifscheiben 125mm K80",
    "Schlösser & Schlüssel/Bartschlüssel":
        "Bartschlüssel[ Rohling][ <Hersteller>] <Nummer>: Bartschlüssel 946-252",
    "Schlösser & Schlüssel/Schlüsselrohlinge & Schlüsselkerne":
        "Schlüsselkerne[ für] <Hersteller> <Nummer/Profil>: Schlüsselkerne Burg 65 R",
    "Technischer Bedarf/Dichtungen & O-Ringe":
        "<Dichtungsart> <Maße>: O-Ring 32x2,5",
    "Technischer Bedarf/Rollen & Räder":
        "<Rollenart>[ <Farbe>][ <Material>] <Durchmesser>mm[ <Befestigung>][ <Tragkraft>]: Bockrolle schwarz Kunststoff 30mm 40kg",
    "Technischer Bedarf/Schmiernippel, Stellringe & Federn":
        "<Teil> <Form/Größe>[ <Gewinde>]: Schmiernippel H1 M10x1",
}


def set_naming(apps, schema_editor):
    """The naming of the default categories, where a category of that full name has none yet."""
    Category = apps.get_model("inventory", "Category")
    for full_name, naming in NAMING.items():
        Category.objects.filter(full_name=full_name, naming="").update(naming=naming)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0048_category_tree"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="naming",
            field=models.TextField(
                blank=True,
                help_text="How items in this category are named, as a pattern with an example, e.g. “Holzschraube <Durchmesser> × <Länge> mm, <Kopfform>: Holzschraube 4 × 40 mm, Senkkopf”.",
                verbose_name="naming",
            ),
        ),
        migrations.RunPython(set_naming, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="changelog",
            name="source",
            field=models.CharField(
                choices=[
                    ("dialog", "Stock dialog"),
                    ("web", "Website"),
                    ("admin", "Admin"),
                    ("dissolution", "Location dissolution"),
                    ("print", "Label printing"),
                    ("cleanup", "Cleanup import"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=20,
                verbose_name="source",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="is_reserved",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="A container whose label was printed in advance. It is hidden until someone scans its label and enters where it is.",
                verbose_name="reserved",
            ),
        ),
        migrations.CreateModel(
            name="CleanupImport",
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
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="uploaded"
                    ),
                ),
                ("file_name", models.CharField(max_length=255, verbose_name="file")),
                (
                    "exported_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="exported"
                    ),
                ),
                ("proposals", models.JSONField(default=dict, verbose_name="proposals")),
                (
                    "decisions",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="decisions"
                    ),
                ),
                (
                    "modified",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="modified changes"
                    ),
                ),
                (
                    "applied_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="applied"),
                ),
                (
                    "result",
                    models.JSONField(blank=True, default=dict, verbose_name="result"),
                ),
                (
                    "applied_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="applied by",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="uploaded by",
                    ),
                ),
            ],
            options={
                "verbose_name": "cleanup import",
                "verbose_name_plural": "cleanup imports",
                "ordering": ["-created_at"],
            },
        ),
    ]
