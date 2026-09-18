from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _


class DeletedObjectFilter(admin.SimpleListFilter):
    title = _("deleted")
    parameter_name = "is_deleted__exact"

    def lookups(self, request, model_admin):
        return [("0", _("Not deleted")), ("1", _("Deleted")), ("all", _("All"))]

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        return queryset.filter(is_deleted=self.value() == "1")

    def choices(self, changelist):
        for value, label in self.lookup_choices:
            yield {
                "selected": (self.value() or "0") == value,
                "query_string": changelist.get_query_string({self.parameter_name: value}),
                "display": label,
            }


class SoftDeleteAdminMixin:
    list_filter = (DeletedObjectFilter,)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not self.has_delete_permission(request, obj):
            fields.append("is_deleted")
        return fields

    def save_model(self, request, obj, form, change):
        if "is_deleted" in form.changed_data and not self.has_delete_permission(request, obj):
            raise PermissionDenied
        super().save_model(request, obj, form, change)

    @admin.display(description=_("deleted"), ordering="is_deleted", empty_value="")
    def deleted_status(self, obj):
        return "❌" if obj.is_deleted else ""

    def get_deleted_objects(self, objs, request):
        objects = list(objs)
        soft = [obj for obj in objects if not obj.is_deleted]
        hard = [obj for obj in objects if obj.is_deleted]
        soft_ids, hard_ids = {obj.pk for obj in soft}, {obj.pk for obj in hard}
        related, counts, perms_needed, protected = super().get_deleted_objects(hard, request)
        displayed = [_("Mark as deleted: %(object)s") % {"object": obj} for obj in soft]
        if related:
            displayed.extend([_("Permanently delete (including related records):"), related])
        counts = dict(counts)
        if soft:
            label = self.opts.verbose_name_plural
            counts[label] = counts.get(label, 0) + len(soft)
        for obj in objects:
            if not self.has_delete_permission(request, obj):
                perms_needed.add(str(self.opts.verbose_name))
            try:
                obj.validate_deletion(hard=obj.is_deleted, soft_ids=soft_ids, hard_ids=hard_ids)
            except ValidationError as error:
                protected.append(f"{obj}: {' '.join(error.messages)}")
        return displayed, counts, perms_needed, protected
