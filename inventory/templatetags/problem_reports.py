from django import template

from ..problem_reports import ProblemReportForm

register = template.Library()


@register.inclusion_tag("inventory/problem_report_modal.html", takes_context=True)
def problem_report_dialog(context):
    """{% problem_report_dialog %}: the dialog "Report a problem" (inventory/problem_reports.py), on every page."""
    request = context["request"]
    return {"form": ProblemReportForm(user=request.user), "request": request, "user": request.user,
            "csrf_token": context.get("csrf_token")}
