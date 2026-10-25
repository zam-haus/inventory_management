from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        from . import change_log
        from .label_ids import naming
        from .models import LabelId

        # Shown in the admin as settings.LABEL_ID_NAME. Set here rather than in Meta, so
        # migrations keep the generic "label ID" whatever an installation calls it.
        LabelId._meta.verbose_name = naming.NAME
        LabelId._meta.verbose_name_plural = naming.PLURAL
        change_log.connect()
