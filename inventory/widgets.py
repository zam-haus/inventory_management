"""Form widgets for the frontend."""
from dal import autocomplete
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext

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
