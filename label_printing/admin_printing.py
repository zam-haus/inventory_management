"""
Printing labels from the admin as the print dialog does (services.print_batch): a page asks which label (or each
the one preselected for it) and how many copies; the printer follows from the label, as in the inventory.
"""
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _, ngettext

from .dialog import BatchPrintForm
from .services import PrintError, print_batch


def report(request, jobs, skipped):
    """Say where the labels print, or that they wait for a printer, and which ones no label is meant for."""
    for job in jobs:
        count = len(job.snapshot) or len(job.request.get("subjects", []))  # waiting jobs are drawn later
        labels = ngettext("%(count)d label", "%(count)d labels", count) % {"count": count}
        if job.printer_id:
            messages.info(request, _("%(labels)s (%(subjects)s): on %(printer)s.") % {
                "labels": labels, "subjects": job.subject_label, "printer": job.printer})
        else:
            messages.warning(request, _("%(labels)s (%(subjects)s) wait for a printer with their labels.") % {
                "labels": labels, "subjects": job.subject_label})
    if skipped:
        messages.warning(request, _("No label is meant for: %(subjects)s.") % {
            "subjects": ", ".join(str(subject) for subject in skipped)})


def print_and_report(request, subject_type, subjects, *, outcome_key="", copies=1):
    """Print and report; False if nothing could be queued."""
    try:
        jobs, skipped = print_batch(subject_type, list(subjects), outcome_key=outcome_key, copies=copies,
                                    user=request.user)
    except PrintError as error:
        messages.error(request, _("The labels could not be printed: %(error)s") % {"error": error})
        return False
    report(request, jobs, skipped)
    return bool(jobs)


def print_page(model_admin, request, subjects, subject_type, *, action=None, title=None):
    """The page asking for label and copies; after printing None (an admin action returns to its list), else
    the page. `action`: the admin action whose selection the page posts again."""
    form = BatchPrintForm(request.POST if "apply" in request.POST else None, subject_type=subject_type)
    if form.is_valid():
        print_and_report(request, subject_type, subjects, outcome_key=form.cleaned_data["label"],
                         copies=form.cleaned_data["copies"])
        return None
    return TemplateResponse(request, "admin/label_printing/print_labels.html", {
        **model_admin.admin_site.each_context(request), "opts": model_admin.model._meta, "form": form,
        "subjects": subjects, "action": action, "title": title or _("Print labels"),
        "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
    })
