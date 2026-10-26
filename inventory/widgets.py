"""Form widgets for the frontend."""
from dal import autocomplete
from django.contrib.admin.widgets import get_select2_language
from django.forms import Media, Select
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext

from . import location_display
from .icons import icon


class AutocompleteSelect(autocomplete.ModelSelect2):
    """
    Autocomplete (Select2) that looks and sizes like a Bootstrap 5 form-select.

    Select2 copies the <select>'s classes onto the box it draws, so the
    "form-select" class lets Bootstrap style that box; autocomplete.css, shipped
    with this widget's media, removes the conflicting Select2 defaults. Use it for
    every autocomplete outside the admin; the admin keeps dal's ModelSelect2.
    """

    class Media:
        css = {"all": ["inventory/autocomplete.css"]}

    def __init__(self, url=None, forward=None, *args, attrs=None, **kwargs):
        attrs = {"data-width": "100%", **(attrs or {})}
        classes = attrs.get("class", "").split()
        if "form-select" not in classes:
            attrs["class"] = " ".join([*classes, "form-select"])
        super().__init__(url, forward, *args, attrs=attrs, **kwargs)


class LocationSelect(AutocompleteSelect):
    """
    Location autocomplete with a QR scan button on its right (location_scan.js): scanning a
    location label or a label ID label selects that location. The search also finds a pasted
    label URL or label ID (views.filter_locations). Use it for every location field outside
    the admin; disabled fields get no button.
    """

    class Media:
        js = ["inventory/location_scan.js"]

    def build_attrs(self, *args, **kwargs):
        """Suggestions and the chosen location as HTML (location_display: title, name, code chip); the views give
        HTML only to these fields (?html=1), the admin's fields get text."""
        attrs = super().build_attrs(*args, **kwargs)
        if url := attrs.get("data-autocomplete-light-url"):
            attrs["data-autocomplete-light-url"] = f"{url}{'&' if '?' in url else '?'}html=1"
        attrs["data-html"] = ""
        return attrs

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        # The chosen location's HTML as the option's text, escaped like any text (a plain str, not safe): Select2
        # shows it as HTML.
        if (location := getattr(value, "instance", None)) is not None:
            label = "".join([location_display.label_html(location)])
        return super().create_option(name, value, label, selected, index, subindex, attrs)

    def render(self, name, value, attrs=None, renderer=None, **kwargs):
        html = super().render(name, value, attrs, renderer, **kwargs)
        if (attrs or {}).get("disabled") or self.attrs.get("disabled"):
            return html
        label = gettext("Scan location label")
        return format_html(
            '<div class="input-group location-scan-group">{}'
            '<span class="disabled-action" tabindex="0" data-bs-toggle="tooltip" title="{}" aria-label="{}">'
            '<button type="button" class="btn btn-secondary location-field-scan" data-location-scan disabled aria-label="{}"'
            ' data-lookup-url="{}" data-title="{}" data-hint="{}" data-added="{}" data-duplicate="{}" data-found="{}">{}</button>'
            '</span></div><div class="form-text" role="status" data-location-scan-status></div>',
            html, gettext("This needs JavaScript."), label, label, reverse("location_lookup"), label,
            gettext("Hold the QR code of a location label in front of the camera."),
            gettext("Scanned: {code}"), gettext("Already scanned: {code}"), gettext("Selected: {location}"),
            icon("qr-code-scan"),
        )


class CategorySelect(Select):
    """
    Item category: with JavaScript (and jQuery on the page) a Select2 field that searches name, path,
    description and keywords and lists the tree indented, each entry with the first line of its description
    (category_select.js); without, a list grouped by top category. The chosen category's description shows
    below the field, so that it is clear what belongs there; describe=False leaves it out (filters). Use it
    for every category field outside the admin.
    """

    chosen_description = ""

    @property
    def media(self):
        i18n = [f"admin/js/vendor/select2/i18n/{language}.js"] if (language := get_select2_language()) else []
        return Media(
            css={"all": ["admin/css/vendor/select2/select2.css", "inventory/autocomplete.css",
                         "inventory/category_select.css"]},
            js=["admin/js/vendor/select2/select2.full.js", *i18n, "inventory/category_select.js"],
        )

    def __init__(self, attrs=None, describe=True):
        super().__init__(attrs)
        self.describe = describe

    def build_attrs(self, *args, **kwargs):
        return {"data-placeholder": gettext("Search or choose a category…"),
                **super().build_attrs(*args, **kwargs), "data-category-select": ""}

    def optgroups(self, name, value, attrs=None):
        selected = {str(v) for v in value if v is not None}
        groups, by_top = [], {}
        self.chosen_description = ""  # for render(), which would otherwise query the categories again
        for index, (option_value, label) in enumerate(self.choices):
            category = getattr(option_value, "instance", None)
            if category is None:  # the empty choice
                groups.append((None, [self.create_option(name, option_value, label, str(option_value) in selected,
                                                         index)], index))
                continue
            top, *path = category.full_name.split("/")
            if top not in by_top:
                by_top[top] = []
                groups.append((top, by_top[top], index))
            if str(option_value) in selected:
                self.chosen_description = category.description
            option = self.create_option(name, option_value, " › ".join(path) or top, str(option_value) in selected,
                                        index, subindex=len(by_top[top]))
            # Select drops attrs given to create_option.
            option["attrs"].update({"data-name": category.name, "data-path": " › ".join([top, *path]),
                                    "data-depth": len(path), "data-description": category.description,
                                    "data-keywords": category.keywords})
            by_top[top].append(option)
        return groups

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)
        if not self.describe:
            return html
        return format_html('{}<div class="form-text category-description" data-category-description>{}</div>',
                           html, self.chosen_description)


NEW_ITEM_PREFIX = "new:"


class ItemOrNewSelect(AutocompleteSelect):
    """
    Item autocomplete whose value may also be "new:<name>": an item that is only
    created when the form is saved (see forms.ItemOrNewField).
    """

    def filter_choices_to_render(self, selected_choices):
        super().filter_choices_to_render([c for c in selected_choices if not c.startswith(NEW_ITEM_PREFIX)])

    def optgroups(self, name, value, attrs=None):
        groups = super().optgroups(name, value, attrs)
        for new in [str(v) for v in value if v and str(v).startswith(NEW_ITEM_PREFIX)]:
            label = gettext("New item “%(name)s”") % {"name": new[len(NEW_ITEM_PREFIX):]}
            groups.append((None, [self.create_option(name, new, label, True, len(groups))], len(groups)))
        return groups
