# Markdown texts

The description of items and the notes of unique items are Markdown, rendered by the `markdown` filter
(`inventory/templatetags/mytemplatetags.py`, only the tags in `MARKDOWN_TAGS`). A text is shown in a section with
its own heading (an h2: "Notes", "About this item"), so its headings go below it: `#` becomes an h3, `##` an h4,
and so on, at most an h6; they are styled smaller than the section's heading.

## Editor

`widgets.MarkdownEditor` renders the field's textarea; `markdown_editor.js` puts the
[TOAST UI Editor](../inventory/static/inventory/vendor/toastui-editor/README.md) (vendored, without its usage
statistics) over it and writes the Markdown back into the textarea, which the form sends. Without
JavaScript the textarea stays. Loading a text into the editor changes nothing; only what people edit is
written back (the editor writes some Markdown differently, e.g. `*` for list items). Resetting the form,
e.g. by closing its dialog, resets the editor. The toolbar offers only what the pages show: headings, bold,
italic, lists and links, in one row that fits a phone; the link popup stays within the editor. On phones the switch
between WYSIWYG and the Markdown source is hidden. Every Markdown field's form uses the widget; a test checks
that.

The editor comes from the logbook branch (`feature/logbook`), taken over unchanged but for one thing: without
an upload URL (`data-markdown-editor` empty, as here) it has no image button and leaves pasted or dropped
images out. Embedded images (their upload, storage and cleanup) come with that branch.

django-autocomplete-light watches the whole page (a MutationObserver on `<html>`) and runs jQuery's `find()` on
every node added anywhere, which briefly sets an `id` on it. In the editor that counts as an edit: the editor draws
anew, adds nodes, and typing hangs in that loop (seen in Firefox, also reproducible in Chrome). `observer_guard.js`,
loaded before dal's script with every autocomplete (`widgets.AutocompleteSelect`), keeps observers of the whole
page out of `[data-observer-private]`, which the editor's holder is; the editor's own observer is unaffected.
