from django.urls import path

from . import api, views

urlpatterns = [
    path("jobs/<int:pk>.json", views.job_status, name="print_job_status"),
    path("api/agent/register", api.register, name="print_agent_register"),
    path("api/agent/poll", api.poll, name="print_agent_poll"),
    path("api/agent/jobs/<int:pk>/result", api.result, name="print_agent_result"),
    # pk: a location's or item's number, or a label ID's code
    path("<str:subject_type>/<str:pk>/", views.PrintLabelsView.as_view(), name="print_labels"),
    path("<str:subject_type>/<str:pk>/preview.png", views.preview, name="print_preview"),
]
