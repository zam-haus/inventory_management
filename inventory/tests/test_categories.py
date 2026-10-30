import importlib

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .. import search
from ..forms import BulkItemForm, NewItemForm, UniqueKindItemForm
from ..label_ids.forms import NewItemForm as ClaimNewItemForm
from ..models import Category, Item, MeasurementUnit

tree_migration = importlib.import_module("inventory.migrations.0048_category_tree")
naming_migration = importlib.import_module("inventory.migrations.0049_cleanup_import")


def paths(nodes, above=()):
    for name, description, children in nodes:
        yield "/".join((*above, name)), description
        yield from paths(children, (*above, name))


def computed_full_name(category):
    return f"{computed_full_name(category.parent_category)}/{category.name}" if category.parent_category else \
        category.name


class CategoryTreeTests(TestCase):
    """The tree the migration creates (0048_category_tree)."""

    def test_default_categories_have_their_naming(self):
        """0049_cleanup_import: the naming of the default categories that have one, each of them in the tree."""
        tree = dict(paths(tree_migration.TREE))
        for full_name, naming in naming_migration.NAMING.items():
            with self.subTest(full_name):
                self.assertIn(full_name, tree)
                self.assertEqual(Category.objects.get(full_name=full_name).naming, naming)
                self.assertIn(": ", naming)  # a pattern, then an example

    def test_every_category_of_the_tree_exists_with_its_description(self):
        for full_name, description in paths(tree_migration.TREE):
            with self.subTest(full_name):
                self.assertEqual(Category.objects.get(full_name=full_name).description, description)

    def test_every_category_has_keywords(self):
        self.assertEqual(set(tree_migration.KEYWORDS), {full_name for full_name, _description in paths(tree_migration.TREE)})
        for category in Category.objects.filter(full_name__in=tree_migration.KEYWORDS):
            self.assertEqual(category.keywords, tree_migration.KEYWORDS[category.full_name])
        self.assertIn("Rohrschelle", Category.objects.get(full_name="Technischer Bedarf/Schellen & Kabelbinder").keywords)

    def test_full_names_match_what_the_model_computes(self):
        for category in Category.objects.select_related("parent_category"):
            self.assertEqual(category.full_name, computed_full_name(category))

    def test_at_most_three_levels_and_unique_names_per_parent(self):
        names = [full_name for full_name, _description in paths(tree_migration.TREE)]
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(max(name.count("/") for name in names), 2)

    def test_every_description_says_what_belongs_there(self):
        for full_name, description in paths(tree_migration.TREE):
            with self.subTest(full_name):
                self.assertTrue(description.strip())
                for line in description.splitlines()[1:]:
                    if line.startswith("Nicht hier:"):
                        # Each target named after an arrow is a category of the tree.
                        for target in line.removeprefix("Nicht hier:").split(";"):
                            if "→" in target:
                                where = target.split("→")[1].strip()
                                self.assertTrue(any(name == where or name.endswith(f"/{where}")
                                                    for name in dict(paths(tree_migration.TREE))), where)


class CategoryFormTests(TestCase):
    def test_choices_are_grouped_by_top_category_with_descriptions(self):
        hinges = Category.objects.get(full_name="Beschläge/Türbeschläge/Türbänder & Bandzubehör")
        item = Item(name="Einbohrband", category=hinges)
        html = str(BulkItemForm(instance=item)["category"])
        self.assertIn('<optgroup label="Beschläge">', html)
        self.assertIn(">Türbeschläge › Türbänder &amp; Bandzubehör</option>", html)
        self.assertIn(f'data-description="{hinges.description[:30]}', html.replace("&amp;", "&"))
        self.assertIn("data-category-description>Einbohr-", html)  # the chosen one's description, without JS

    def test_the_chosen_categorys_naming_shows_below_it(self):
        hinges = Category.objects.get(full_name="Beschläge/Türbeschläge/Türbänder & Bandzubehör")
        hinges.naming = "<Art>band <Länge> mm: Einbohrband 13 mm"
        hinges.save()
        html = str(BulkItemForm(instance=Item(name="Einbohrband", category=hinges))["category"])
        self.assertIn('data-naming="&lt;Art&gt;band &lt;Länge&gt; mm: Einbohrband 13 mm"', html)  # for the script
        # Below the field, without the script too (the widget speaks German here).
        self.assertIn('<div class="form-text category-naming" data-category-naming><strong>Benennung:</strong> '
                      '<span>&lt;Art&gt;band &lt;Länge&gt; mm: Einbohrband 13 mm</span></div>', html)
        other = Category.objects.exclude(pk=hinges.pk).first()
        self.assertIn("data-category-naming hidden>", str(BulkItemForm(instance=Item(category=other))["category"]))

    def test_the_category_comes_before_the_name(self):
        for form in (BulkItemForm(), UniqueKindItemForm(), NewItemForm()):
            with self.subTest(form=type(form).__name__):
                fields = list(form.fields)
                self.assertLess(fields.index("category"), fields.index("name"))
                layout = [pointer.name for pointer in form.helper.layout.get_field_names()]
                self.assertLess(layout.index("category"), layout.index("name"))

    def test_options_carry_what_the_search_shows(self):
        drawers = Category.objects.get(full_name="Beschläge/Möbelbeschläge/Rohrkappen & Stopfen")
        html = str(BulkItemForm()["category"])
        self.assertIn(f'<option value="{drawers.pk}" data-name="Rohrkappen &amp; Stopfen" '
                      'data-path="Beschläge › Möbelbeschläge › Rohrkappen &amp; Stopfen" data-depth="2"', html)
        self.assertIn('data-placeholder="', html)
        self.assertIn('data-keywords="Rohrkappe, Rohrstopfen,', html)

    def test_item_page_loads_the_search_after_jquery(self):
        # crispy-forms would put the form's media inside the form, before the page loads jQuery.
        user = get_user_model().objects.create_superuser(username="admin", password="x")
        self.client.force_login(user)
        html = self.client.get(reverse("create_item")).content.decode()
        self.assertEqual(html.count("select2/select2.full.js"), 1)
        self.assertLess(html.index("static_jquery/js/jquery.min.js"), html.index("select2/select2.full.js"))

    def test_search_assets_come_with_the_field(self):
        media = str(BulkItemForm().media)
        self.assertIn("select2.full.js", media)
        self.assertLess(media.index("select2.full.js"), media.index("category_select.js"))

    def test_claim_page_uses_the_same_choice(self):
        self.assertIn("data-category-select", str(ClaimNewItemForm()["category"]))

    def test_choice_needs_one_query(self):
        form = BulkItemForm()
        with self.assertNumQueries(1):
            str(form["category"])


class CategoryFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        unit, _ = MeasurementUnit.objects.get_or_create(pk=1, defaults={"name": "Piece", "short": "pc"})
        cls.hinge = Item.objects.create(name="Einbohrband 15 mm", measurement_unit=unit, category=Category.objects.get(
            full_name="Beschläge/Türbeschläge/Türbänder & Bandzubehör"))
        cls.hook = Item.objects.create(name="Wandhaken", measurement_unit=unit,
                                       category=Category.objects.get(full_name="Beschläge/Haken & Ösen"))
        cls.screw = Item.objects.create(name="Spax 4x40", measurement_unit=unit,
                                        category=Category.objects.get(full_name="Befestigungstechnik/Holzschrauben"))
        # A category whose name starts like another one's must not count as below it.
        cls.lookalike = Category.objects.create(name="Beschläge alt")
        cls.old = Item.objects.create(name="Altes Band", measurement_unit=unit, category=cls.lookalike)

    def test_search_finds_items_by_a_category_above(self):
        found = {(entry.kind, entry.title) for entry in search.render.entries(search.search("Türbeschläge").hits)}
        # The category itself and the one whose name contains it are hits, too.
        self.assertEqual(found, {("item", "Einbohrband 15 mm"), ("category", "Türbeschläge"),
                                 ("category", "Schiebetürbeschläge")})


class CategoryTreeMigrationTests(TransactionTestCase):
    def test_earlier_categories_become_nodes_of_the_tree(self):
        before = [("inventory", "0047_reserved_containers")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            Category_ = apps.get_model("inventory", "Category")
            Category_.objects.all().delete()

            def make(name, parent=None, description=""):
                full_name = f"{parent.full_name}/{name}" if parent else name
                return Category_.objects.create(name=name, parent_category=parent, full_name=full_name,
                                                description=description)

            abrasives = make("Schleifmittel", description="Benennung:\r\n* K# Körnung")
            standard = make("Normteile")
            wood = make("Holzschrauben", standard)
            machine = make("Maschinenschrauben", standard)
            own = make("Eigenes")
            below = make("Unterkategorie", standard)
            unit = apps.get_model("inventory", "MeasurementUnit").objects.get_or_create(
                pk=1, defaults={"name": "Piece", "short": "pc"})[0]
            item = apps.get_model("inventory", "Item").objects.create(name="M6", measurement_unit=unit,
                                                                         category=machine)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            categories = {category.pk: category for category in Category.objects.select_related("parent_category")}
            self.assertEqual(categories[abrasives.pk].full_name, "Oberfläche & Chemie/Schleifmittel")
            self.assertIn("Benennung:\n* K# Körnung", categories[abrasives.pk].description)
            self.assertTrue(categories[abrasives.pk].description.startswith("Schleifmittel zum"))
            self.assertEqual(categories[standard.pk].full_name, "Befestigungstechnik")
            self.assertEqual(categories[wood.pk].full_name, "Befestigungstechnik/Holzschrauben")
            self.assertEqual(categories[machine.pk].full_name, "Befestigungstechnik/Metrische Schrauben")
            self.assertIn("Madenschraube", Category.objects.get(
                full_name="Befestigungstechnik/Metrische Schrauben/DIN 913–916 Gewindestifte").keywords)
            self.assertIn("Maschinenschraube", categories[machine.pk].keywords)
            self.assertEqual(categories[own.pk].full_name, "Eigenes")
            self.assertEqual(categories[below.pk].full_name, "Befestigungstechnik/Unterkategorie")
            self.assertEqual(Item.objects.get(pk=item.pk).category_id, machine.pk)
            self.assertEqual(Category.objects.filter(full_name="Befestigungstechnik").count(), 1)
            for category in categories.values():
                self.assertEqual(category.full_name, computed_full_name(category))
        finally:
            MigrationExecutor(connection).migrate(latest)
