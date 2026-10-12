"""Form widgets for the frontend."""
from dal import autocomplete
from django.utils.translation import gettext


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
