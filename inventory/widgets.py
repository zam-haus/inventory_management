"""Form widgets for the frontend."""
from dal import autocomplete


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
