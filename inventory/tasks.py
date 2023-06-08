import logging

from celery import shared_task
from django.apps import apps

from inventory.models import ItemImage

logger = logging.getLogger(__name__)


@shared_task
def run_ocr_on_item_image(pk):
    logger.info(f"Running OCR on image {pk}")
    item_image = ItemImage.objects.get(pk=pk)
    item_image.run_ocr()
    item_image.save_ocr_text()
