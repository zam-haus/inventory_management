from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ZamIdConfig(AppConfig):
    name = "zamid"
    verbose_name = _("ZAM IDs")
    default_auto_field = "django.db.models.BigAutoField"
