from random import randint, choice

from django.utils import timezone
from django.db import transaction
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, DetailView, UpdateView
from django.views.generic.edit import DeleteView
from django.core.exceptions import ObjectDoesNotExist
import extra_views
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Q
from dal import autocomplete
from . import forms
from . import models

# Create your views here.


def index(request):
    return render(request, "inventory/index.html")

class LocationAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Do not forget to filter out results depending on the logged-in user or other criteria
        if not self.request.user.is_authenticated:
            return models.Location.objects.none()

        qs = models.Location.objects.all()

        # `self.q` is the search term from the user, provided by DAL.
        if self.q:
            query = self.q
            qs = qs.filter(
                Q(name__icontains=query) | 
                Q(unique_identifier__icontains=query)
            )

        return qs

class DetailLocationView(DetailView):
    model = models.Location
    # (request, pk, unique_identifier):
    # Prio 1
    # return HttpResponse("Here should be an overview of items stored at this location.")

    # TODO
    # * inform user, if redirect with changed unique_identifier occurred

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if "unique_identifier" in kwargs and self.object.unique_identifier != kwargs["unique_identifier"]:
            return redirect(self.object)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)


def update_location(request, pk, unique_identifier):
    pass

class LocationMoveView(UpdateView):
    template_name = 'inventory/location_move.html'
    form_class = forms.LocationMoveForm
    model = models.Location
    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)

    def get(self, request, *args, **kwargs):
        if not self.get_object().type.moveable:
            return HttpResponseForbidden("This Location is not allowed to be moved in the Frontend.")
        return super().get(request, *args, **kwargs)
    def post(self, request, *args, **kwargs):
        if not self.get_object().type.moveable:
            return HttpResponseForbidden("This Location is not allowed to be moved in the Frontend.")
        return super().post(request, *args, **kwargs)

def view_item(request, pk):
    return redirect(reverse_lazy("update_item", args=[pk]))
class DetailItemView(DetailView):
    model = models.Item


def category_json(request, pk):
    c = models.Category.objects.get(pk=pk)
    return JsonResponse({
        'name': c.name,
        'full_name': c.full_name,
        'description': c.description,
        'parent_category': c.parent_category.pk if c.parent_category else None,
    })

class CreateItemView(UserPassesTestMixin, extra_views.CreateWithInlinesView):
    model = models.Item
    inlines = [forms.ItemImageInline, forms.ItemLocationInline]
    template_name = "inventory/item_formset.html"
    form_class = forms.ItemForm
    extra_context = {"title": _("Create Item")}

    def get_success_url(self):
        location = self._get_location()
        if location is not None \
                and self.request.POST and "save_and_mark" in self.request.POST:
            # redirect to location
            return reverse_lazy('view_location', args=[location.id, location.unique_identifier])
        # Preserve location_id
        url = reverse_lazy("create_item")
        if self.request.GET and "location_id" in self.request.GET and location:
            url += "?location_id=%s" % self._get_location().id
        return url
    
    def _get_location(self):
        if self.request.GET and "location_id" in self.request.GET:
            location_id = self.request.GET.get("location_id")
            try:
                location_id = int(location_id)
                return models.Location.objects.get(pk=location_id)
            except (ValueError, models.Location.DoesNotExist):
                pass
        return None

    def get_context_data(self, **kwargs):
        ctxt = super().get_context_data(**kwargs)
        location = self._get_location()
        if location is not None:
            ctxt['location'] = location
        return ctxt

    def construct_inlines(self):
        location = self._get_location()
        if location is not None:
            self.kwargs["initial"] = [{"location": location}]
        return super().construct_inlines()
    
    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local')


class UpdateItemView(UserPassesTestMixin, extra_views.UpdateWithInlinesView):
    model = models.Item
    inlines = [forms.ItemImageInline, forms.ItemLocationInline]
    template_name = "inventory/item_formset.html"
    form_class = forms.ItemForm  # Changed to ItemForm
    factory_kwargs = {
        "extra": 1, #possible usage for additional related
    }
    extra_context = {"title": _("Update Item")}

    def get_success_url(self):
        return self.object.get_absolute_url()

    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)


class AnnotateItemView(UserPassesTestMixin, UpdateView):
    model = models.Item
    template_name = "inventory/item_annotate_form.html"
    form_class = forms.ItemLocationForm
    factory_kwargs = {
        "extra": 1, #possible usage for additional related item
    }
    extra_context = {"title": _("Update Item")}

    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)

    def get_success_url(self):
        if self.request.POST and "save_next" in self.request.POST:
            # redirect to next incomplete
            incomplete = models.Item.filter_incomplete(ordered=True)
            next_incomplete = incomplete & models.Item.objects.filter(pk__gt=self.object.pk)
            if not next_incomplete:
                next_incomplete = incomplete
            return reverse_lazy("annotate_item", args=[incomplete[randint(0, incomplete.count() -1)].pk])
        return reverse_lazy("annotate_item", args=[self.object.pk])


class SearchableItemListView(ListView):
    model = models.Item
    exact_query = False
    wrong_lookup = False
    paginate_by = 25
    template_name = "inventory/item_list.html"

    def get_context_data(self):
        ctxt = super().get_context_data()
        incomplete = models.Item.filter_incomplete()
        if (len(incomplete) != 0):
            ctxt.update({
                'incomplete_count': incomplete.count(),
                'incomplete_first_pk': incomplete[randint(0, incomplete.count() - 1)].pk
            })
        return ctxt
    def get_queryset(self):
        try:
            queryset = super().get_queryset()
            query = self.request.GET.get('q')
            if query:
                queryset = queryset.filter(
                    Q(name__icontains=query) |
                    Q(description__icontains=query) |
                    Q(category__name__icontains=query) |
                    Q(itemlocation__location__unique_identifier__icontains=query) |
                    Q(itemlocation__location__name__icontains=query) |
                    Q(itemimage__ocr_text__icontains=query)
                )
            return queryset
        except Exception as e:
            # Log the error
            print(f"Error in SearchableItemListView: {str(e)}")
            # Return empty queryset instead of failing
            return self.model.objects.none()


    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)


class SearchableLocationListView(
        UserPassesTestMixin,
        extra_views.SearchableListMixin,
        extra_views.SortableListMixin,
        ListView):
    # matching criteria can be defined along with fields
    search_fields = ["locatable_identifier", "name", "descriptive_identifier"]
    search_date_fields = []
    sort_fields = ["unique_identifier"]
    model = models.Location
    exact_query = False
    wrong_lookup = False
    paginate_by = 100

    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)


#class DeleteItemView(UserPassesTestMixin, DeleteView):
#    model = models.Item
#    success_url = reverse_lazy('index_items')
#    template_name = 'inventory/item_confirm_delete.html'
#
#    def test_func(self):
#        return not self.request.user.is_anonymous or \
#            self.request.session.get('is_zam_local', False)


class ParentLocationAutocompleteView(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return models.Location.objects.none()
        qs = models.Location.objects.filter(type__no_sublocations = False)
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(unique_identifier__icontains=self.q))
        return qs

    def get_results(self, context):
        self_id_str = self.forwarded.get('id', None)
        if self_id_str == None:
            return super().get_results(context)
        try:
            self_id = int(self_id_str)
        except ValueError:
            self_id = 0
        if self_id == 0:
            return super().get_results(context)
        sorted_out = [self_id]
        while True:
            old_count = len(sorted_out)
            sorted_out.extend([x.pk for x in context['object_list'] if x.pk not in sorted_out and x.parent_location != None and x.parent_location.pk in sorted_out])
            new_count = len(sorted_out)
            if (old_count == new_count):
                break
        context['object_list'] = [x for x in context['object_list'] if x.pk not in sorted_out]
        return super().get_results(context)
