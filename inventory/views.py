from random import randint, choice

from django.utils import timezone
from django.db import transaction
from django.http import HttpResponse, JsonResponse
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
from .models import Location

from . import forms
from . import models

# Create your views here.


def index(request):
    return render(request, "inventory/index.html")

# adding the search based on select2

def search_location(request):
    """Handle AJAX search requests for locations"""
    try:
        search_term = request.GET.get('term', '') or request.GET.get('q', '')
        print(f"Searching for: {search_term}")  # Debug log
        
        # Fetch locations matching the search term
        locations = Location.objects.filter(
            Q(name__icontains=search_term) | 
            Q(unique_identifier__icontains=search_term)
        )
        print(f"Found {locations.count()} locations")  # Debug log
        
        # Format results for Select2
        results = [{
            'id': loc.id,
            'text': f"{loc.name} [{loc.unique_identifier}]"
        } for loc in locations]
        
        return JsonResponse({
            'results': results,
            'pagination': {'more': False}
        })
    except Exception as e:
        print(f"Error in search_location: {str(e)}")  # Debug log
        return JsonResponse({'error': str(e)}, status=500)


class DetailLocationView(DetailView):
    model = models.Location
    # (request, pk, unique_identifier):
    # Prio 1
    # return HttpResponse("Here should be an overview of items stored at this location.")

    # TODO
    # * inform user, if redirect with changed unique_identifier occurred

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.unique_identifier != kwargs["unique_identifier"]:
            return redirect(self.object)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)


def update_location(request, pk, unique_identifier):
    pass


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
        "extra": 1,
        "can_order": False,
        "can_delete": False,
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
    actory_kwargs = {
        "extra": 1,
        "can_order": False,
        "can_delete": False,
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
            return reverse_lazy("annotate_item", args=[incomplete[randint(0, incomplete.count())].pk])
        return reverse_lazy("annotate_item", args=[self.object.pk])


class SearchableItemListView(ListView):
    model = models.Item
    paginate_by = 50
    template_name = "inventory/item_list.html"

    def get_queryset(self):
        try:
            queryset = super().get_queryset()
            query = self.request.GET.get('q')
            if query:
                queryset = queryset.filter(
                    models.Q(name__icontains=query) |
                    models.Q(description__icontains=query)
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


class DeleteItemView(UserPassesTestMixin, DeleteView):
    model = models.Item
    success_url = reverse_lazy('index_items')
    template_name = 'inventory/item_confirm_delete.html'

    def test_func(self):
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)
