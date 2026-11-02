"""Create locations of area-numbered types (such as shelves) on a location page.

On one page the type is chosen first (with its drawing and text, LocationType.numbering_drawing and numbering_info),
then the number: a free number reserved for this area (the next one first), a
wished-for number that nobody uses or reserves, or a new number assigned automatically. A wished-for or new
number creates as many as asked for at once, each alike, or only reserves the following numbers for this area
(LocationNumberRange, reserve_only). The location's sub-locations, such as a shelf's compartments, can be created along
with it.

Containers (boxes, cartons, pallets) simply get the next number of their type (ContainerCreateView).
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MaxValueValidator
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from .forms import ContainerActivationForm
from .models import Location, LocationNumberRange, LocationType

COMPUTED = ["unique_identifier", "locatable_identifier", "descriptive_identifier"]
RESERVED, WISH, AUTO = "reserved", "wish", "auto"
MAX_CONTAINERS = 50  # created at once
MAX_ALL = 50  # numbered locations created at once


class NumberedLocationForm(forms.Form):
    mode = forms.ChoiceField(label=_("Number"), widget=forms.RadioSelect)
    reserved = forms.ChoiceField(label=_("Reserved number"), required=False)
    wish = forms.IntegerField(label=_("Wished-for number"), required=False, min_value=0)
    count = forms.IntegerField(label=_("How many, from this number on?"), required=False, min_value=1,
                               max_value=LocationNumberRange.MAX_RESERVATION, initial=1)
    reserve_only = forms.BooleanField(label=_("Only reserve the following numbers"), required=False)
    sublocations = forms.IntegerField(required=False, min_value=0, initial=0)
    purpose = forms.CharField(label=_("Purpose"), max_length=50, required=False)
    description = forms.CharField(
        label=_("Description"), required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("What it looks like and how it is built, e.g. colour, material, size or number of shelves."))

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
        # Several at once: each alike, without a purpose (it differs from one to the next; set on their pages).
        alike = (_("each with as many %(sub)s and the description below, without a purpose") % {"sub": sub.name}
                 if sub and sub.auto_sequence else _("each with the description below, without a purpose"))
        self.fields["count"].help_text = _(
            "More than 1: this one and the following free numbers, %(alike)s; at most %(max)s at once.") % {
            "alike": alike, "max": MAX_ALL}
        self.fields["reserve_only"].help_text = _(
            "For a wished-for or new number: only this one is created, the following numbers up to the count are "
            "reserved for this area, for later (at most %(max)s).") % {"max": LocationNumberRange.MAX_RESERVATION}
        if sub and sub.auto_sequence:
            self.fields["sublocations"].label = _("Number of %(type)s inside") % {"type": sub.name}
            self.fields["sublocations"].help_text = on_top_hint(kind)
            self.fields["sublocations"].validators.append(MaxValueValidator(sub.MAX_SUBLOCATIONS))
            self.fields["sublocations"].widget.attrs["max"] = sub.MAX_SUBLOCATIONS
        else:
            del self.fields["sublocations"]

    FIELDS_FOR = {RESERVED: {"reserved", "count"}, WISH: {"wish", "count", "reserve_only"},
                  AUTO: {"count", "reserve_only"}}

    def extend(self, cleaned, count):
        """More than the reservation holds from the chosen number on: the numbers right behind its range, if no
        location uses them and no range covers them; that range then grows by them (cleaned["extend"]: the range
        and its new last number)."""
        numbers = cleaned["numbers"]
        source = self.parent.number_range_source(self.kind)
        number_range = next(r for r in source.number_ranges.filter(type=self.kind) if r.first <= numbers[-1] <= r.last)
        first, last = number_range.last + 1, number_range.last + count - len(numbers)
        upper = 10 ** (self.kind.auto_short_name_padding_length or 3) - 1
        blocked = sorted(LocationNumberRange.unavailable(self.kind, first, last))
        if last > upper or blocked:
            self.add_error("count", _("Only %(count)s reserved numbers from %(number)s on are free, and the numbers "
                                      "right after the reservation %(range)s are used or reserved.") % {
                "count": len(numbers), "number": numbers[0], "range": number_range})
            return
        cleaned["numbers"] = numbers + list(range(first, last + 1))
        cleaned["extend"] = (number_range, last)

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        # Only the fields of the chosen way count; whatever else was entered is ignored.
        for name in {"reserved", "wish", "count", "reserve_only"} - self.FIELDS_FOR.get(mode, set()):
            self._errors.pop(name, None)
            cleaned.pop(name, None)
        count = cleaned.get("count") or 1
        created = 1 if cleaned.get("reserve_only") else count
        if created > MAX_ALL:
            self.add_error("count", _("At most %(max)s can be created at once.") % {"max": MAX_ALL})
        if mode == RESERVED:
            if cleaned.get("reserved") not in self.free:
                self.add_error("reserved", _("Choose one of the reserved numbers."))
            elif count <= MAX_ALL:
                chosen = int(cleaned["reserved"])
                cleaned["numbers"] = sorted(n for n in map(int, self.free) if n >= chosen)[:count]
                if len(cleaned["numbers"]) < count:
                    self.extend(cleaned, count)
        elif mode == WISH:
            wish = cleaned.get("wish")
            if wish is None:
                self.add_error("wish", _("Enter the number you want."))
            else:
                blocked = sorted(LocationNumberRange.unavailable(self.kind, wish, wish + count - 1))
                if blocked and blocked[0] == wish:
                    self.add_error("wish", _("%(number)s is already used or reserved.") % {"number": wish})
                elif blocked:
                    self.add_error("count", _("Only %(count)s numbers from %(number)s on are free.") % {
                        "count": blocked[0] - wish, "number": wish})
        # Several at once get no purpose (the field hides then, numbered_location.js).
        if created > 1:
            cleaned["purpose"] = ""
        return cleaned


class NumberedLocationCreateView(PermissionRequiredMixin, FormView):
    permission_required = "inventory.add_location"
    template_name = "inventory/numbered_location_create.html"
    form_class = NumberedLocationForm

    def dispatch(self, request, *args, **kwargs):
        self.parent = get_object_or_404(Location.active.select_related("type"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def kinds(self):
        kinds = [kind for kind, _source in self.parent.numbering_types()]
        if self.parent.type.no_sublocations or not kinds:
            raise PermissionDenied
        return kinds

    @cached_property
    def kind(self):
        """The type chosen (?type=, also posted), at first the first one: the form is one page, the type its first
        field (numbered_location_create.html)."""
        kinds = {str(kind.pk): kind for kind in self.kinds()}
        chosen = self.request.POST.get("type") or self.request.GET.get("type")
        if chosen is None:
            return next(iter(kinds.values()))
        if chosen not in kinds:
            raise Http404
        return kinds[chosen]

    def get_template_names(self):
        # Another type chosen: only what depends on it (numbered_location.js).
        if self.request.GET.get("partial"):
            return ["inventory/numbered_location_fields.html"]
        return [self.template_name]

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "parent": self.parent, "kind": self.kind}

    def get_context_data(self, **kwargs):
        source = self.parent.number_range_source(self.kind)
        ranges = ", ".join(str(r) for r in source.number_ranges.filter(type=self.kind)) if source else ""
        return super().get_context_data(object=self.parent, kind=self.kind, kinds=self.kinds(), source=source,
                                        ranges=ranges, url=reverse("numbered_location_create", args=[self.parent.pk]),
                                        **kwargs)

    def form_valid(self, form):
        kind, data, reservation = self.kind, form.cleaned_data, None
        # Numbers are reserved for the room or area, also for shelves created on a pallet there.
        area = self.parent.numbering_area()
        try:
            with transaction.atomic():
                if data["mode"] == RESERVED:
                    number = int(data["reserved"])
                    numbers = data["numbers"]
                    if data.get("extend"):
                        reservation, last = data["extend"]
                        reservation.last = last
                        reservation.save()
                else:
                    count = data.get("count") or 1
                    if data["mode"] == WISH:
                        number = data["wish"]
                        if count > 1:
                            reservation = LocationNumberRange.objects.create(
                                location=area, type=kind, first=number, last=number + count - 1)
                    else:
                        reservation = self.reserve_new(area, kind, count, bool(form.free))
                        number = next(n for n, _name, _short in self.parent.free_numbers(kind)
                                      if reservation.first <= n <= reservation.last)
                    # All numbers of the range, from this one on, each alike; or only this one, the others reserved.
                    numbers = [number] if data.get("reserve_only") or reservation is None else [
                        n for n, _name, _short in self.parent.free_numbers(kind) if number <= n <= reservation.last]
                created = [self.create(kind, n, data) for n in numbers]
        except (ValidationError, IntegrityError) as error:
            form.add_error(None, " ".join(getattr(error, "messages", [])) or
                           _("The number was taken in the meantime. Choose another one."))
            return self.form_invalid(form)
        location, parts = created[0]
        if len(created) > 1:
            locations = [entry for entry, _parts in created]
            text = _("%(count)s × %(type)s created: %(first)s to %(last)s.") % {
                "count": len(created), "type": kind.name, "first": locations[0].short_name,
                "last": locations[-1].short_name}
            if parts:
                text += " " + _("Each with %(count)s %(type)s.") % {
                    "count": len(parts), "type": kind.sublocation_type.name}
            if data.get("extend"):
                text += " " + _("The reservation of %(place)s now covers %(range)s.") % {
                    "place": reservation.location.name, "range": reservation}
            messages.success(self.request, text)
            new = [new_location for entry, entry_parts in created for new_location in [entry, *entry_parts]]
            return redirect(with_print_dialog(self.request, self.parent, new))
        text = _("%(name)s created.") % {"name": location.name}
        if reservation:
            text += " " + _("Numbers %(range)s are reserved for %(type)s at %(place)s.") % {
                "range": reservation, "type": kind.name, "place": reservation.location.name}
        if parts:
            text += " " + _("%(count)s %(type)s added.") % {"count": len(parts), "type": kind.sublocation_type.name}
        messages.success(self.request, text)
        return purposes_url_or(self.request, location, parts, [location] + parts)

    def create(self, kind, number, data):
        """(the location of `kind` with `number`, its sub-locations)."""
        name, short = kind.numbered_names(number)
        location = Location(type=kind, name=name, short_name=short, parent_location=self.parent,
                            purpose=data["purpose"], description=data["description"])
        location.full_clean(exclude=COMPUTED + ["overview_photo"])
        location.save(actor=self.request.user)
        return location, self.create_sublocations(location, data.get("sublocations") or 0)

    def reserve_new(self, area, kind, count, keep_reserved):
        """A new range of `count` numbers for `area`; behind a used-up range if possible, otherwise in a free gap."""
        if not keep_reserved:
            return LocationNumberRange.reserve(area, kind, count)
        suggestion = LocationNumberRange.suggest(kind, area, size=count)
        if suggestion is None:
            raise ValidationError(_("There is no room for %(count)s more numbers here. Ask the inventory admins.")
                                  % {"count": count})
        return LocationNumberRange.objects.create(location=area, type=kind, first=suggestion[0],
                                                  last=suggestion[1])

    def create_sublocations(self, location, count):
        """Creates `count` sub-locations of the type's sub type in `location`; returns them."""
        sub = location.type.sublocation_type
        if not sub or not count:
            return []
        return [Location.objects.create(type=sub, name=name, short_name=short, parent_location=location)
                for name, short in sub.free_sublocation_names(location, count)]


class ContainerCreateForm(forms.Form):
    type = forms.ModelChoiceField(label=_("What is added?"), queryset=LocationType.objects.none(),
                                  widget=forms.RadioSelect, empty_label=None)
    count = forms.IntegerField(
        label=_("How many?"), required=False, min_value=1, max_value=MAX_CONTAINERS, initial=1,
        help_text=_("Several get the next free numbers, from the one shown on; each gets the purpose and "
                    "description below."))
    purpose = NumberedLocationForm.base_fields["purpose"]
    description = NumberedLocationForm.base_fields["description"]

    def __init__(self, *args, parent, **kwargs):
        super().__init__(*args, **kwargs)
        kinds = parent.container_types()
        field = self.fields["type"]
        field.queryset = LocationType.objects.filter(pk__in=[kind.pk for kind in kinds]).order_by("name")
        # Each choice shows the number it gets now; saving takes the next free one again.
        nexts = {kind.pk: kind.next_free_number() for kind in kinds}
        field.label_from_instance = lambda kind: f"{kind.name} · {nexts[kind.pk][2]}"
        if len(kinds) == 1:
            field.initial = kinds[0].pk


class ContainerCreateView(PermissionRequiredMixin, FormView):
    """Boxes, cartons and pallets: no number to choose, they get the next one of their type."""
    permission_required = "inventory.add_location"
    template_name = "inventory/container_create.html"
    form_class = ContainerCreateForm

    def dispatch(self, request, *args, **kwargs):
        self.parent = get_object_or_404(Location.active.select_related("type"), pk=kwargs["pk"])
        if not self.parent.container_types():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("type"):
            initial["type"] = self.request.GET["type"]
        return initial

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "parent": self.parent}

    def get_context_data(self, **kwargs):
        return super().get_context_data(object=self.parent, **kwargs)

    def form_valid(self, form):
        kind, data = form.cleaned_data["type"], form.cleaned_data
        try:
            with transaction.atomic():
                created = [self.create_container(kind, data) for _index in range(data.get("count") or 1)]
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
            return self.form_invalid(form)
        if len(created) == 1:
            location = created[0]
            messages.success(self.request, _("%(name)s (%(code)s) created.") % {
                "name": location.name, "code": location.short_name})
            return redirect(with_print_dialog(self.request, location, created))
        messages.success(self.request, _("%(count)s × %(type)s created: %(codes)s.") % {
            "count": len(created), "type": kind.name, "codes": ", ".join(entry.short_name for entry in created)})
        return redirect(with_print_dialog(self.request, self.parent, created))

    def create_container(self, kind, data):
        return create_numbered_container(kind, parent=self.parent, purpose=data["purpose"],
                                         description=data["description"], actor=self.request.user)


def create_numbered_container(kind, *, parent=None, reserved=False, purpose="", description="", actor=None):
    """The next container of `kind`, with the next free number; reserved ones (no parent) wait for activation."""
    for _attempt in range(3):
        try:
            with transaction.atomic():
                _number, name, short = kind.next_free_number()
                location = Location(type=kind, name=name, short_name=short, parent_location=parent,
                                    is_reserved=reserved, purpose=purpose, description=description)
                location.full_clean(exclude=COMPUTED + ["overview_photo"])
                location.save(actor=actor)
            return location
        except IntegrityError:
            continue  # someone took the number in the meantime: take the next one
    raise ValidationError(_("The number was taken in the meantime. Try again."))


class ContainerActivateView(FormView):
    """A reserved container (preprinted label, ReserveContainersAdminView) taken into use: whoever may create
    locations says where it is; until then it is hidden. Its label and code searches lead here."""
    template_name = "inventory/container_activate.html"
    form_class = ContainerActivationForm
    permission = "inventory.add_location"

    def dispatch(self, request, *args, **kwargs):
        self.object = get_object_or_404(Location.objects.select_related("type"), pk=kwargs["pk"], is_deleted=False)
        if not self.object.is_reserved:
            return redirect(self.object)
        return super().dispatch(request, *args, **kwargs)

    def can_activate(self):
        return self.request.user.has_perm(self.permission)

    def next_url(self):
        url = self.request.POST.get("next") or self.request.GET.get("next")
        if url and url_has_allowed_host_and_scheme(url, {self.request.get_host()}, require_https=self.request.is_secure()):
            return url
        return None

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.object}

    def get_context_data(self, **kwargs):
        return super().get_context_data(object=self.object, can_activate=self.can_activate(),
                                        next=self.next_url() or "", **kwargs)

    def post(self, request, *args, **kwargs):
        if not self.can_activate():
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            raise PermissionDenied
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            # Two people scanning the same label: the first one activates it.
            if not Location.objects.select_for_update().filter(pk=self.object.pk, is_reserved=True).exists():
                messages.info(self.request, _("%(name)s has been activated in the meantime.") % {"name": self.object.name})
                return redirect(self.object)
            location = form.save(commit=False)
            location.is_reserved = False
            location.save(actor=self.request.user)
        messages.success(self.request, _("%(name)s (%(code)s) is now in use, at %(location)s.") % {
            "name": location.name, "code": location.short_name, "location": location.parent_location.title_with_code})
        return redirect(self.next_url() or location.get_absolute_url())


class SublocationAddForm(forms.Form):
    count = forms.IntegerField(min_value=1, initial=1)

    def __init__(self, *args, parent, **kwargs):
        super().__init__(*args, **kwargs)
        sub = parent.type.sublocation_type
        self.next = sub.free_sublocation_names(parent, 3)
        self.fields["count"].label = _("How many %(type)s to add?") % {"type": sub.name}
        self.fields["count"].help_text = on_top_hint(parent.type)
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
            parts = [Location.objects.create(type=sub, name=name, short_name=short, parent_location=self.parent)
                     for name, short in names]
        messages.success(self.request, _("%(count)s %(type)s added: %(codes)s.") % {
            "count": len(names), "type": sub.name, "codes": ", ".join(short for _name, short in names)})
        return purposes_url_or(self.request, self.parent, parts, parts)


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
        self.new = new_locations(request.GET.get("print") or request.POST.get("print") or "")
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
                                        codes=",".join(code for code in self.codes if code),
                                        new=",".join(map(str, self.new)),
                                        done_url=with_print_dialog(self.request, self.parent, self.new), **kwargs)

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
        return redirect(with_print_dialog(self.request, self.parent, self.new))


def on_top_hint(kind):
    """The hint at a count of compartments: the top of the shelf or cabinet is one too (numbering/shelf.html); below a
    table, its top and above it count as well (numbering/table.html)."""
    if kind.numbering_drawing == LocationType.Drawing.TABLE:
        return _("Below the %(type)s counts as the first one, its top and, if there is something above it, that one "
                 "as the last ones.") % {"type": kind.name}
    return _("The top of the %(type)s counts as one too if things are put on it: it gets the last letter.") % {
        "type": kind.name}


def purposes_url_or(request, location, parts, new):
    """Where to go after adding compartments `parts`: their purposes, if the user may set them, else the location;
    either way then the label print dialog for the `new` locations."""
    if parts and request.user.has_perm("inventory.change_location"):
        codes = ",".join(part.short_name for part in parts)
        url = reverse("sublocation_purposes", args=[location.pk]) + "?codes=" + codes
        return redirect(url + ("&" + printing if (printing := print_query(request, new)) else ""))
    return redirect(with_print_dialog(request, location, new))


def new_locations(value):
    """The pks in a comma-separated `print` parameter."""
    return [int(pk) for pk in value.split(",") if pk.strip().isdigit()]


def print_query(request, new):
    """`print=<pks>` for the label print dialog with the `new` locations (or pks) checked; "" for whoever may not
    print (label_printing) and if nothing is new."""
    if not new or not request.user.has_perm("label_printing.print_label"):
        return ""
    return "print=" + ",".join(str(getattr(entry, "pk", entry)) for entry in new)


def with_print_dialog(request, location, new):
    """`location`'s page, opening the label print dialog with the labels of the `new` locations checked: the
    location itself and its sub-locations."""
    url = location.get_absolute_url()
    return url + "?" + printing if (printing := print_query(request, new)) else url
