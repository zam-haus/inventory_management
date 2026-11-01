from django.test import SimpleTestCase

from ..forms import BulkItemForm, NewItemForm, UniqueItemForm, UniqueKindItemForm
from ..widgets import AutocompleteSelect, LocationSelect, MarkdownEditor


class MarkdownEditorTests(SimpleTestCase):
    """Markdown fields are edited with the WYSIWYG editor (docs/markdown.md); without image uploads for now."""

    def test_markdown_fields_use_the_editor(self):
        for form, name in ((BulkItemForm, "description"), (UniqueKindItemForm, "description"),
                           (NewItemForm, "description"), (UniqueItemForm, "notes")):
            with self.subTest(form=form.__name__):
                self.assertIsInstance(form.base_fields[name].widget, MarkdownEditor)

    def test_the_editor_has_no_image_upload_yet(self):
        html = MarkdownEditor().render("notes", "**bold**")
        self.assertIn('data-markdown-editor=""', html)
        self.assertIn("**bold**", html)
        self.assertIn("inventory/markdown_editor.js", str(MarkdownEditor().media))

    def test_the_observer_guard_comes_before_dal(self):
        # dal watches the whole page from the moment its script runs; it must not see the editor's own changes
        # (observer_guard.js), or typing hangs in a loop of the two (Firefox).
        for widget in (AutocompleteSelect(url="location-autocomplete"), LocationSelect(url="location-autocomplete")):
            scripts = [script._path for script in widget.media._js]
            dal = next(index for index, path in enumerate(scripts)
                       if path.startswith("autocomplete_light/autocomplete_light"))  # .min.js without DEBUG
            self.assertLess(scripts.index("inventory/observer_guard.js"), dal)
        self.assertIn("inventory/autocomplete.css", str(AutocompleteSelect(url="location-autocomplete").media))

    def test_headings_lie_below_the_section(self):
        # Shown in a section with its own h2 ("Notes", "About this item"): # becomes an h3, and so on, at most h6.
        from ..templatetags.mytemplatetags import render_markdown
        self.assertEqual(render_markdown("# One\n## Two\n##### Five\n###### Six").split("\n"),
                         ["<h3>One</h3>", "<h4>Two</h4>", "<h6>Five</h6>", "<h6>Six</h6>"])

