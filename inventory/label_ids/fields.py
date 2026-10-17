"""Model and form fields that store canonical label IDs and accept any typed or scanned form."""
from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import core, parsing

ERROR_MESSAGES = {
    "malformed": _("Invalid ID."),
    "checksum": _("Check symbol does not match – typo?"),
}


def to_canonical(value):
    """Normalize typed or scanned input; raise ValidationError with a code per failure."""
    try:
        return parsing.code_from_scan(value)
    except core.InvalidLabelId as e:
        reason = e.args[0]
        raise ValidationError(ERROR_MESSAGES[reason], code=reason)


class LabelIdInput(forms.TextInput):
    """Shows canonical values in display form (K7R-4XD)."""

    def __init__(self, attrs=None):
        super().__init__({"autocomplete": "off", "spellcheck": "false", "placeholder": "K7R-4XD", **(attrs or {})})

    def format_value(self, value):
        if value and core.is_valid(value):
            return core.display(value)
        return super().format_value(value)


class LabelIdFormField(forms.CharField):
    widget = LabelIdInput

    def __init__(self, **kwargs):
        kwargs.pop("max_length", None)
        super().__init__(max_length=200, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return to_canonical(value)


class LabelIdField(models.CharField):
    description = _("label ID")

    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = core.ID_LEN
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return to_canonical(value)

    def get_prep_value(self, value):
        # Lenient for lookups: invalid input simply matches nothing. Skips CharField's
        # to_python(), which is strict here. Six symbols are taken as a stored code and
        # matched exactly, so codes from an earlier alphabet are still found (lookalikes
        # are not mapped); other input (display forms, URLs) is normalized first.
        value = models.Field.get_prep_value(self, value)
        if isinstance(value, str):
            stored = value.strip().upper()
            if len(stored) == core.ID_LEN and all(c.isalnum() for c in stored):
                return stored
            try:
                return parsing.code_from_scan(value)
            except core.InvalidLabelId:
                return stored
        return value

    def pre_save(self, model_instance, add):
        # Strict for storage: only canonical, valid IDs are ever written.
        value = getattr(model_instance, self.attname)
        if not (isinstance(value, str) and core.is_valid(value)):
            raise ValueError(f"not a canonical label ID: {value!r}")
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{"form_class": LabelIdFormField, **kwargs})
