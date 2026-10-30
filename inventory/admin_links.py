"""The admin page that belongs to the page shown: where the navbar's Admin link leads ({% admin_page_url %}, base.html).

In this order, each only if the user may see that admin page, else the next:
1. the object the page is about (the context's "object", or another name registered with register_object_name):
   its change page;
2. a page that creates something (a view of a model without object yet): the add page of its model;
3. a page of a model (the view's `model`): its list;
4. a page registered by URL name (register_page): that model's list or that app's page;
5. the admin's start page.
Optional apps register their pages in AppConfig.ready() (e.g. maps), so the inventory never imports them. A page can
still override `{% block admin_url %}` when none of this fits.
"""
from django.apps import apps
from django.contrib import admin
from django.contrib.admin.utils import quote
from django.db.models import Model
from django.urls import NoReverseMatch, reverse

_object_names = ["object", "lid"]
_pages = {}


def register_object_name(name):
    """A context name under which a page passes the object it is about (besides "object")."""
    if name not in _object_names:
        _object_names.append(name)


def register_page(url_name, target):
    """The admin page for a page without an object of its own: "app_label.model" for that model's list, or
    "app_label" for the app's page in the admin."""
    _pages[url_name] = target


register_page("index_items", "inventory.item")
register_page("index_locations", "inventory.location")
register_page("structure_overview", "inventory.location")


def _admin_url(name, *args, **kwargs):
    try:
        return reverse(f"admin:{name}", args=args, kwargs=kwargs)
    except NoReverseMatch:
        return None


def _model_url(request, model, action, obj=None):
    model_admin = admin.site._registry.get(model)
    if model_admin is None:
        return None
    opts = model._meta
    if action == "change":
        allowed = model_admin.has_view_or_change_permission(request, obj)
        args = [quote(obj.pk)]
    elif action == "add":
        allowed = model_admin.has_add_permission(request)
        args = []
    else:
        allowed = model_admin.has_view_or_change_permission(request)
        args = []
    return _admin_url(f"{opts.app_label}_{opts.model_name}_{action}", *args) if allowed else None


def _page_url(request, target):
    if "." in target:
        try:
            model = apps.get_model(target)
        except LookupError:
            return None
        return _model_url(request, model, "changelist")
    if request.user.has_module_perms(target):
        return _admin_url("app_list", app_label=target)
    return None


def admin_page_url(context):
    request = context.get("request")
    if request is None:
        return reverse("admin:index")
    view = context.get("view")
    for name in _object_names:
        obj = context.get(name)
        if isinstance(obj, Model) and obj.pk is not None:
            url = _model_url(request, type(obj), "change", obj)
            if url:
                return url
    model = getattr(view, "model", None)
    if model is not None:
        # Create views (Django's, extra_views') have no object yet; detail and update views have one.
        creates = hasattr(view, "object") and view.object is None
        url = _model_url(request, model, "add" if creates else "changelist")
        if url:
            return url
    match = getattr(request, "resolver_match", None)
    target = _pages.get(match.url_name) if match else None
    if target:
        url = _page_url(request, target)
        if url:
            return url
    return reverse("admin:index")
