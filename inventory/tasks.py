import logging

from celery import shared_task
from django.apps import apps
logger = logging.getLogger(__name__)


@shared_task
def run_ocr_on_item_image(pk):
    logger.warning(f"Running OCR on image {pk}")
    item_image = apps.get_model('inventory', 'ItemImage').objects.get(pk=pk)
    item_image.run_ocr()
    item_image.save_ocr_text()
