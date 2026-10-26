from django import forms
from django.utils.translation import gettext_lazy as _

from inventory.models import Location

from .levels import Tree, label
from .models import FloorPlan


class FloorPlanForm(forms.ModelForm):
    level = forms.TypedChoiceField(label=_("Level"), coerce=int, help_text=_(
        "Levels with the same number lie at about the same height in every house and share one map; a level can "
        "have several plans (e.g. one per house)."))

    class Meta:
        model = FloorPlan
        fields = ("level", "location", "name", "source", "page", "dpi", "notes")
        widgets = {"source": forms.FileInput(attrs={"accept": ".pdf,.png,.jpg,.jpeg,.webp,.svg"}),
                   "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tree = Tree()
        self.fields["level"].choices = [(number, f"{label(number)} ({', '.join(tree.code(pk) for pk in pks)})")
                                        for number, pks in sorted(tree.levels().items(), reverse=True)]
        # Only parts of stacked areas: plans of whole levels belong to no location.
        self.fields["location"].queryset = Location.active.filter(
            parent_location__map_shape__parts_stacked=True).order_by("unique_identifier")
        self.fields["location"].required = False
