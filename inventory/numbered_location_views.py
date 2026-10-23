"""Create locations of area-numbered types (such as shelves) on a location page.

First the type is chosen, then the number: a free number reserved for this area (the next one first), a
wished-for number that nobody uses or reserves, or a new number assigned automatically. A wished-for or new
number reserves as many following numbers as are to be expected here (LocationNumberRange). The location's
sub-locations, such as a shelf's compartments, can be created along with it.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MaxValueValidator
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from .models import Location, LocationNumberRange

COMPUTED = ["unique_identifier", "locatable_identifier", "descriptive_identifier"]
RESERVED, WISH, AUTO = "reserved", "wish", "auto"


class NumberedLocationForm(forms.Form):
    mode = forms.ChoiceField(label=_("Number"), widget=forms.RadioSelect)
    reserved = forms.ChoiceField(label=_("Reserved number"), required=False)
    wish = forms.IntegerField(label=_("Wished-for number"), required=False, min_value=0)
    expected = forms.IntegerField(
        label=_("How many are to be expected here in total, this one included?"), required=False,
        min_value=1, max_value=LocationNumberRange.MAX_RESERVATION, initial=10,
        help_text=_("For a wished-for or new number: that many consecutive numbers are reserved for this "
                        "area. With 1, only this number is used."),
    )
    sublocations = forms.IntegerField(required=False, min_value=0, initial=0)
    purpose = forms.CharField(label=_("Purpose"), max_length=50, required=False)

    def __init__(self, *args, parent, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent, self.kind = parent, kind
        self.free = {str(number): (name, short) for number, name, short in parent.free_numbers(kind)}
        modes = [(WISH, _("Wished-for number")), (AUTO, _("New number, assigned automatically"))]
        if self.free:
            modes.insert(0, (RESERVED, _("Reserved number")))
            self.fields["reserved"].choices = [(number, f"{short} · {name}") for number, (name, short) in self.free.items()]
        else:
            del self.fields["reserved"]
        self.fields["mode"].choices = modes
        self.fields["mode"].initial = modes[0][0]
        sub = kind.sublocation_type
        if sub and sub.auto_sequence:
            self.fields["sublocations"].label = _("Number of %(type)s inside") % {"type": sub.name}
            self.fields["sublocations"].validators.append(MaxValueValidator(sub.MAX_SUBLOCATIONS))
            self.fields["sublocations"].widget.attrs["max"] = sub.MAX_SUBLOCATIONS
        else:
            del self.fields["sublocations"]

    FIELDS_FOR = {RESERVED: {"reserved"}, WISH: {"wish", "expected"}, AUTO: {"expected"}}

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        # Only the fields of the chosen way count; whatever else was entered is ignored.
        for name in {"reserved", "wish", "expected"} - self.FIELDS_FOR.get(mode, set()):
            self._errors.pop(name, None)
            cleaned.pop(name, None)
        expected = cleaned.get("expected") or 1
        if mode == RESERVED:
            if cleaned.get("reserved") not in self.free:
                self.add_error("reserved", _("Choose one of the reserved numbers."))
        elif mode == WISH:
            wish = cleaned.get("wish")
            if wish is None:
                self.add_error("wish", _("Enter the number you want."))
            else:
                blocked = sorted(LocationNumberRange.unavailable(self.kind, wish, wish + expected - 1))
                if blocked and blocked[0] == wish:
                    self.add_error("wish", _("%(number)s is already used or reserved.") % {"number": wish})
                elif blocked:
                    self.add_error("expected", _("Only %(count)s numbers from %(number)s on are free.") % {
                        "count": blocked[0] - wish, "number": wish})
        elif mode == AUTO and not cleaned.get("expected"):
            self.add_error("expected", _("Say how many are to be expected here."))
        return cleaned


class NumberedLocationCreateView(PermissionRequiredMixin, FormView):
    permission_required = "inventory.add_location"
    template_name = "inventory/numbered_location_create.html"
    form_class = NumberedLocationForm

    def dispatch(self, request, *args, **kwargs):
        self.parent = get_object_or_404(Location.active.select_related("type"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def kinds(self):
        if self.parent.type.no_sublocations or not self.parent.type.structure:
            raise PermissionDenied
        return [kind for kind, _source in self.parent.numbering_types()]

    @property
    def kind(self):
        kinds = {str(kind.pk): kind for kind in self.kinds()}
        chosen = self.request.GET.get("type") or self.request.POST.get("type")
        if chosen is None and len(kinds) == 1:
            return next(iter(kinds.values()))
        if chosen is not None and chosen not in kinds:
            raise Http404
        return kinds.get(chosen)

    def get(self, request, *args, **kwargs):
        if self.kind is None:  # step 1: what is created
            return self.render_to_response({"object": self.parent, "view": self, "kinds": self.kinds(),
                                            "url": reverse("numbered_location_create", args=[self.parent.pk])})
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        if self.kind is None:
            raise Http404
        return {**super().get_form_kwargs(), "parent": self.parent, "kind": self.kind}

    def get_context_data(self, **kwargs):
        source = self.parent.number_range_source(self.kind)
        ranges = ", ".join(str(r) for r in source.number_ranges.filter(type=self.kind)) if source else ""
        return super().get_context_data(object=self.parent, kind=self.kind, source=source, ranges=ranges, **kwargs)

    def form_valid(self, form):
        kind, data, reservation = self.kind, form.cleaned_data, None
        try:
            with transaction.atomic():
                if data["mode"] == RESERVED:
                    number = int(data["reserved"])
                elif data["mode"] == WISH:
                    number = data["wish"]
                    if (data.get("expected") or 1) > 1:
                        reservation = LocationNumberRange.objects.create(
                            location=self.parent, type=kind, first=number, last=number + data["expected"] - 1)
                else:
                    reservation = self.reserve_new(kind, data["expected"], bool(form.free))
                    number = next(n for n, _name, _short in self.parent.free_numbers(kind)
                                  if reservation.first <= n <= reservation.last)
                name, short = kind.numbered_names(number)
                location = Location(type=kind, name=name, short_name=short, parent_location=self.parent,
                                    purpose=data["purpose"])
                location.full_clean(exclude=COMPUTED + ["overview_photo"])
                location.save(actor=self.request.user)
                parts = self.create_sublocations(location, data.get("sublocations") or 0)
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, " ".join(getattr(error, "messages", [])) or
                           _("The number was taken in the meantime. Choose another one."))
            return self.form_invalid(form)
        text = _("%(name)s created.") % {"name": location.name}
        if reservation:
            text += " " + _("Numbers %(range)s are reserved for %(type)s at %(place)s.") % {
                "range": reservation, "type": kind.name, "place": reservation.location.name}
        if parts:
            text += " " + _("%(count)s %(type)s added.") % {"count": len(parts), "type": kind.sublocation_type.name}
        messages.success(self.request, text)
        return purposes_url_or(self.request, location, parts)

    def reserve_new(self, kind, count, keep_reserved):
        """A new range of `count` numbers; behind a used-up range if possible, otherwise in a free gap."""
        if not keep_reserved:
            return LocationNumberRange.reserve(self.parent, kind, count)
        suggestion = LocationNumberRange.suggest(kind, self.parent, size=count)
        if suggestion is None:
            raise ValidationError(_("There is no room for %(count)s more numbers here. Ask the inventory admins.")
                                  % {"count": count})
        return LocationNumberRange.objects.create(location=self.parent, type=kind, first=suggestion[0],
                                                  last=suggestion[1])

    def create_sublocations(self, location, count):
        """Creates `count` sub-locations of the type's sub type in `location`; returns their codes."""
        sub = location.type.sublocation_type
        if not sub or not count:
            return []
        names = sub.free_sublocation_names(location, count)
        for name, short in names:
            Location.objects.create(type=sub, name=name, short_name=short, parent_location=location)
        return [short for _name, short in names]


class SublocationAddForm(forms.Form):
    count = forms.IntegerField(min_value=1, initial=1)

    def __init__(self, *args, parent, **kwargs):
        super().__init__(*args, **kwargs)
        sub = parent.type.sublocation_type
        self.next = sub.free_sublocation_names(parent, 3)
        self.fields["count"].label = _("How many %(type)s to add?") % {"type": sub.name}
        self.fields["count"].validators.append(MaxValueValidator(sub.MAX_SUBLOCATIONS))
        self.fields["count"].widget.attrs["max"] = sub.MAX_SUBLOCATIONS


class SublocationAddView(PermissionRequiredMixin, FormView):
    """More compartments (the type's sub-locations) in an existing shelf or cabinet, with the next free letters."""
    permission_required = "inventory.add_location"
    template_name = "inventory/sublocation_add.html"
    form_class = SublocationAddForm

    def dispatch(self, request, *args, **kwargs):
        self.parent = get_object_or_404(Location.active.select_related("type__sublocation_type"), pk=kwargs["pk"])
        if self.parent.type.sublocation_type is None or self.parent.type.no_sublocations:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "parent": self.parent}

    def get_context_data(self, **kwargs):
        sub = self.parent.type.sublocation_type
        existing = self.parent.children.filter(is_deleted=False, type=sub).order_by("short_name")
        return super().get_context_data(object=self.parent, sub=sub, existing=existing, **kwargs)

    def form_valid(self, form):
        sub = self.parent.type.sublocation_type
        with transaction.atomic():
            names = sub.free_sublocation_names(self.parent, form.cleaned_data["count"])
            for name, short in names:
                Location.objects.create(type=sub, name=name, short_name=short, parent_location=self.parent)
        messages.success(self.request, _("%(count)s %(type)s added: %(codes)s.") % {
            "count": len(names), "type": sub.name, "codes": ", ".join(short for _name, short in names)})
        return purposes_url_or(self.request, self.parent, [short for _name, short in names])


class SublocationPurposeForm(forms.Form):
    """One purpose per compartment, e.g. right after they were added; listed top down like they sit (a at the bottom)."""

    def __init__(self, *args, parts, **kwargs):
        super().__init__(*args, **kwargs)
        validators = Location._meta.get_field("purpose").validators
        for part in reversed(parts):
            self.fields[f"purpose_{part.pk}"] = forms.CharField(
                label=f"{part.short_name} · {part.name}", max_length=50, required=False, initial=part.purpose,
                validators=validators, widget=forms.TextInput(attrs={"placeholder": _("Purpose")}))


class SublocationPurposeView(PermissionRequiredMixin, FormView):
    """Purposes of a shelf's compartments (its type's sub-locations); `codes` limits it to some of them."""
    permission_required = "inventory.change_location"
    template_name = "inventory/sublocation_purposes.html"
    form_class = SublocationPurposeForm

    def dispatch(self, request, *args, **kwargs):
        self.parent = get_object_or_404(Location.active.select_related("type__sublocation_type"), pk=kwargs["pk"])
        if self.parent.type.sublocation_type is None:
            raise Http404
        self.codes = (request.GET.get("codes") or request.POST.get("codes") or "").split(",")
        return super().dispatch(request, *args, **kwargs)

    def parts(self):
        parts = self.parent.children.filter(is_deleted=False, type=self.parent.type.sublocation_type)
        wanted = [code for code in self.codes if code]
        return sorted(parts.filter(short_name__in=wanted) if wanted else parts,
                      key=lambda part: (len(part.short_name), part.short_name))

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "parts": self.parts()}

    def get_context_data(self, **kwargs):
        return super().get_context_data(object=self.parent, sub=self.parent.type.sublocation_type,
                                        codes=",".join(code for code in self.codes if code), **kwargs)

    def form_valid(self, form):
        changed = 0
        with transaction.atomic():
            for part in self.parts():
                purpose = form.cleaned_data.get(f"purpose_{part.pk}", "")
                if purpose != part.purpose:
                    part.purpose = purpose
                    part.save(actor=self.request.user, update_fields=["purpose"])
                    changed += 1
        if changed:
            messages.success(self.request, _("Purposes saved."))
        return redirect(self.parent)


def purposes_url_or(request, location, codes):
    """Where to go after adding compartments: their purposes, if the user may set them, else the location."""
    if codes and request.user.has_perm("inventory.change_location"):
        return redirect(reverse("sublocation_purposes", args=[location.pk]) + "?codes=" + ",".join(codes))
    return redirect(location)
