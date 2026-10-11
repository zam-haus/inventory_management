"""Model and form fields that store canonical ZAM IDs and accept any typed or scanned form."""
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
    except core.InvalidZamId as e:
        reason = e.args[0]
        raise ValidationError(ERROR_MESSAGES[reason], code=reason)


class ZamIdInput(forms.TextInput):
    """Shows canonical values in display form (K7Q-4XD)."""

    def __init__(self, attrs=None):
        super().__init__({"autocomplete": "off", "spellcheck": "false", "placeholder": "K7Q-4XD", **(attrs or {})})

    def format_value(self, value):
        if value and core.is_valid(value):
            return core.display(value)
        return super().format_value(value)


class ZamIdFormField(forms.CharField):
    widget = ZamIdInput

    def __init__(self, **kwargs):
        kwargs.pop("max_length", None)
        super().__init__(max_length=200, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return to_canonical(value)


class ZamIdField(models.CharField):
    description = _("ZAM ID")

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
        # Lenient for lookups: invalid input simply matches nothing.
        value = super().get_prep_value(value)
        if isinstance(value, str):
            try:
                return parsing.code_from_scan(value)
            except core.InvalidZamId:
                return value.strip().upper()
        return value

    def pre_save(self, model_instance, add):
        # Strict for storage: only canonical, valid IDs are ever written.
        value = getattr(model_instance, self.attname)
        if not (isinstance(value, str) and core.is_valid(value)):
            raise ValueError(f"not a canonical ZAM ID: {value!r}")
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{"form_class": ZamIdFormField, **kwargs})
