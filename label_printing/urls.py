from django.urls import path

from . import api, views

urlpatterns = [
    path("jobs/<int:pk>.json", views.job_status, name="print_job_status"),
    path("batches/<uuid:batch>.json", views.batch_status, name="print_batch_status"),
    path("api/agent/poll", api.poll, name="print_agent_poll"),
    path("api/agent/jobs/<int:pk>/result", api.result, name="print_agent_result"),
    path("api/agent/printers/loaded", api.loaded, name="print_agent_loaded"),
    path("api/agent/printers/ribbon", api.ribbon, name="print_agent_ribbon"),
    path("api/agent/printers/own-label", api.own_label, name="print_agent_own_label"),
    path("api/agent/printers/offsets", api.offsets, name="print_agent_offsets"),
    path("api/agent/jobs/<int:pk>/cancel", api.cancel, name="print_agent_cancel"),
    path("api/agent/jobs/<int:pk>/extend", api.extend, name="print_agent_extend"),
    path("api/agent/jobs/<int:pk>/detail", api.detail, name="print_agent_job_detail"),
    path("api/agent/jobs/<int:pk>/reprint", api.reprint, name="print_agent_reprint"),
    path("templates/preview", views.design_preview, name="label_design_preview"),
    path("templates/help", views.design_help, name="label_design_help"),
    path("templates/<int:pk>/sample.png", views.template_sample, name="label_template_sample"),
    path("templates/<int:pk>/<str:subject_type>/<str:subject_pk>.png", views.template_preview,
         name="label_template_preview"),
    # pk: a location's or item's number, or a label ID's code
    path("<str:subject_type>/<str:pk>/", views.PrintLabelsView.as_view(), name="print_labels"),
    path("<str:subject_type>/<str:pk>/preview.png", views.preview, name="print_preview"),
]
