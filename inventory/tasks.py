from celery import shared_task
from django.utils import timezone

from .models import ItemImage
from .ocr_util import ocr_on_image_path


@shared_task(name="inventory.tasks.recognize_text", ignore_result=True)
def recognize_text(image_id):
    """Recognize the text on a new or replaced photo (queue ocr, ItemImage.save). Skips photos deleted or already
    recognized meanwhile (manage.py ocr)."""
    image = ItemImage.objects.filter(pk=image_id, ocr_timestamp__isnull=True).first()
    if not image or not image.image:
        return
    text = ocr_on_image_path(image.image.path)
    # Only if the file is still the same: a photo replaced meanwhile gets its own task. An update, not save(), so
    # changes made to the photo meanwhile are kept.
    ItemImage.objects.filter(pk=image.pk, image=image.image.name).update(ocr_text=text, ocr_timestamp=timezone.now())
