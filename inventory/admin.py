from email.policy import default
from random import choices
from django.contrib import admin
from django import forms
from django.urls import path
from django.db.models import TextField, CharField
from django.db import IntegrityError
from django.template.response import TemplateResponse
from django.views.generic import FormView
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages


from . import models

# Register your models here.
admin.site.register(models.LocationType)
admin.site.register(models.Category)
admin.site.register(models.MeasurementUnit)
admin.site.register(models.BarcodeType)


class LocationLabelTemplateAdmin(admin.ModelAdmin):
    model = models.LocationLabelTemplate
    fields = ("name", "zpl_template", "label_width", "label_height", "image_tag")
    readonly_fields = ("image_tag",)


admin.site.register(models.LocationLabelTemplate, LocationLabelTemplateAdmin)


class LocationInline(admin.TabularInline):
    model = models.Location
    verbose_name = "location's child"
    verbose_name_plural = "location's children"

    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 1, "cols": 30})},
        CharField: {"widget": forms.TextInput(attrs={"size": 20})},
    }


class LocationAdmin(admin.ModelAdmin):
    list_display = ("locatable_identifier", "name", "descriptive_identifier")
    fields = (
        "type",
        "name",
        "short_name",
        "description",
        "parent_location",
        "label_template",
        "label_image_tag",
        "last_complete_inventory",
    )
    ordering = ("locatable_identifier",)
    readonly_fields = ("label_image_tag",)
    search_fields = ('locatable_identifier', 'name')
    actions = ["send_to_printer_action"]
    inlines = [LocationInline]
    inlines_popup = []

    def get_inlines(self, request, obj):
        if "_to_field" in request.GET and "_popup" in request.GET:
            return []
        else:
            return self.inlines

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta.app_label, self.model._meta.model_name
        my_urls = [
            path(
                "<path:object_id>/massadd/",
                MassAddLocationsAdminView.as_view(),
                name="%s_%s_massadd" % info,
            ),
            path(
                "massadd/",
                MassAddLocationsAdminView.as_view(),
                name="%s_%s_massadd" % info,
            ),
            path(
                "<path:object_id>/print-label/",
                self.send_to_printer_view,
                name="%s_%s_print-label" % info,
            ),
        ]
        return my_urls + urls

    def mass_add_view(self, request, object_id=None):
        class MassAddForm(forms.Form):
            location_type = forms.ModelChoiceField(
                label="location type",
                required=True,
                queryset=models.LocationType.objects.all(),
            )
            parent = forms.ModelChoiceField(
                label="Parent location", queryset=models.Location.objects.all()
            )
            sequence_start = forms.CharField(max_length=32)

            sub_count = forms.IntegerField(label="Sub-location count")
            sub_type = forms.ModelChoiceField(
                label="Sub-location type",
                required=True,
                queryset=models.LocationType.objects.all(),
            )

        if request.method == "POST":
            form = MassAddForm(request.POST)
        else:
            form = MassAddForm()

        context = dict(
            # Include common variables for rendering the admin template.
            self.admin_site.each_context(request),
            content=form.as_p(),
        )
        return TemplateResponse(
            request, "admin/inventory/location_massadd.html", context
        )

    @method_decorator(staff_member_required)
    def send_to_printer_view(self, request, object_id=None):
        try:
            models.Location.objects.get(pk=object_id).send_to_printer()
            messages.add_message(request, messages.INFO, "Sent label to printer.")
        except Exception as e:
            messages.add_message(
                request, messages.ERROR, "Failed sending label to printer: {}".format(e)
            )
        return redirect(
            reverse(
                "admin:%s_%s_change"
                % (self.model._meta.app_label, self.model._meta.model_name),
                args=[object_id],
            )
        )

    @admin.action(description="Print location labels")
    def send_to_printer_action(self, request, queryset):
        sucesses, fails = 0, []
        for loc in queryset:
            try:
                loc.send_to_printer()
                successes += 1
            except Exception as e:
                fails.append(str(e))
        if successes:
            messages.add_message(
                request, messages.INFO, "Sent {} label(s) to printer.".format(successes)
            )
        if fails:
            for emsg in set(fails):
                messages.add_message(
                    request,
                    messages.ERROR,
                    "Failed sending {} label(s) to printer: {}".format(
                        fails.count(emsg), emsg
                    ),
                )


admin.site.register(models.Location, LocationAdmin)


class MassAddLocationsForm(forms.Form):
    parent_location = forms.ModelChoiceField(
        label="Parent location", queryset=models.Location.objects.all()
    )
    location_type = forms.ModelChoiceField(
        label="Location type", required=True, queryset=models.LocationType.objects.all()
    )
    label_template = forms.ModelChoiceField(
        label="Overwrite default location label template",
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sequence_start = forms.CharField(max_length=32)
    count = forms.IntegerField()
    print = forms.BooleanField(label="print main lables", required=False)

    sub_type = forms.ModelChoiceField(
        label="Sub-location type",
        required=False,
        queryset=models.LocationType.objects.all(),
    )
    sub_label_template = forms.ModelChoiceField(
        label="Overwrite default sub-location label template",
        required=False,
        queryset=models.LocationLabelTemplate.objects.all(),
    )
    sub_count = forms.IntegerField(label="Sub-location count", required=False)
    sub_print = forms.BooleanField(label="print sub-location labels", required=False)

    def clean_sub_type(self):
        sub_type = self.cleaned_data["sub_type"]
        if sub_type and sub_type.unique and self.cleaned_data["sub_count"]:
            raise ValidationError(
                "Sub-Type must be a non-unique type, if sub-location count is >0."
            )
        return sub_type


class MassAddLocationsAdminView(FormView):
    form_class = MassAddLocationsForm
    template_name = "admin/inventory/location_massadd.html"
    success_url = "/admin/inventory/location"

    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context.update(admin.site.each_context(request))
        return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, form):
        data = form.cleaned_data
        print(data)
        # create a list of locations
        loc_type = data["location_type"]
        sub_type = data["sub_type"]

        # create locations
        for name, short_name in loc_type.generate_names(
            data["count"], start=data["sequence_start"]
        ):
            l = models.Location()
            l.name = name
            l.short_name = short_name
            l.type = loc_type
            l.parent_location = data["parent_location"]
            l.label_template = data["label_template"] or None
            l.save()
            if data["print"]:
                l.send_to_printer()

            # create sub-locations
            print(sub_type)
            if sub_type is not None:
                print("subtype")
                for name, short_name in sub_type.generate_names(data["sub_count"]):
                    print(name, short_name)
                    sl = models.Location()
                    sl.name = name
                    sl.short_name = short_name
                    sl.type = sub_type
                    sl.parent_location = l
                    sl.label_template = data["sub_label_template"] or None
                    sl.save()
                    if data["sub_print"]:
                        sl.send_to_printer()

        return super().form_valid(form)


class ItemLocationInline(admin.TabularInline):
    model = models.ItemLocation
    extra = 1


class ItemBarcodeInline(admin.TabularInline):
    model = models.ItemBarcode
    extra = 1
    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 1, "cols": 30})},
    }


class ItemImageInline(admin.TabularInline):
    model = models.ItemImage
    extra = 1


class ItemFileInline(admin.TabularInline):
    model = models.ItemFile
    extra = 0


class ItemAdmin(admin.ModelAdmin):
    inlines = [ItemBarcodeInline, ItemImageInline, ItemFileInline, ItemLocationInline]
    formfield_overrides = {
        TextField: {"widget": forms.Textarea(attrs={"rows": 3, "cols": 60})},
    }


admin.site.register(models.Item, ItemAdmin)
