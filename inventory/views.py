from audioop import reverse
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, DetailView
from django.core.exceptions import ObjectDoesNotExist
import extra_views
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.mixins import UserPassesTestMixin


from . import forms
from . import models

# Create your views here.


def index(request):
    return render(request, "inventory/index.html")


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


def create_item(request):
    # Prio 0
    # get location_id from request
    context = {}

    item_form = forms.CreateItemForm()
    context["form"] = item_form
    return render(request, "inventory/create_item.html", context)


def update_item(request, id):
    # Prio 3
    pass


def delete_item(request, id):
    # Prio 5
    pass


def update_location(request, pk, unique_identifier):
    # Prio 4
    pass


def view_item(request, pk):
    return redirect(reverse_lazy("update_item", args=[pk]))


class CreateItemView(UserPassesTestMixin, extra_views.CreateWithInlinesView):
    model = models.Item
    inlines = [forms.ItemImageInline, forms.ItemLocationInline]
    template_name = "inventory/item_formset.html"
    form_class = forms.CreateItemForm
    extra_context = {"title": _("Create Item")}

    def get_success_url(self):
        url = reverse_lazy("create_item")
        # Preserve location_id
        if self.request.GET and "location_id" in self.request.GET:
            url += "?location_id=%s" % self.request.GET.get("location_id")
        return url

    def construct_inlines(self):
        try:
            location = models.Location.objects.get(
                pk=self.request.GET.get("location_id")
            )
            self.kwargs["initial"] = [{"location": location}]
        except ObjectDoesNotExist:
            pass
        return super().construct_inlines()
    
    def test_func(self):
        # Logged in or @ZAM
        print(not self.request.user.is_anonymous, self.request.session.get('is_zam_local', False))
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local')


class UpdateItemView(UserPassesTestMixin, extra_views.UpdateWithInlinesView):
    model = models.Item
    inlines = [forms.ItemImageInline, forms.ItemLocationInline]
    template_name = "inventory/item_formset.html"
    form_class = forms.ItemForm
    extra_context = {"title": _("Update Item")}

    def get_success_url(self):
        return self.object.get_absolute_url()

    def test_func(self):
        # Logged in or @ZAM
        print(not self.request.user.is_anonymous,
              self.request.session.get('is_zam_local', False))
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)


class SearchableItemListView(UserPassesTestMixin, extra_views.SearchableListMixin, ListView):
    # matching criteria can be defined along with fields
    search_fields = ["name", "category__name"]
    search_date_fields = []
    model = models.Item
    exact_query = False
    wrong_lookup = False

    # def get_search_query(self):
    #    # Overwrite query here
    #    return super().get_search_query()

    def test_func(self):
        # Logged in or @ZAM
        return not self.request.user.is_anonymous or \
            self.request.session.get('is_zam_local', False)
