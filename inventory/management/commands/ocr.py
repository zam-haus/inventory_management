import logging
import multiprocessing as mp
import os
import sys
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from tqdm import tqdm

from inventory.models import ItemImage
from inventory.ocr_util import ocr_on_image_path

logger = logging.getLogger("ocr")
logger.handlers.clear()
logger.setLevel(logging.INFO)

def limit_tesseract_threads():
    # several tesseract processes run in parallel; each one spawning a thread per core multiplies memory use
    os.environ["OMP_THREAD_LIMIT"] = "1"

def run_ocr(id_with_path):
    image_id, path = id_with_path
    return (image_id, ocr_on_image_path(path))

class Command(BaseCommand):
    help = "Runs OCR on item images"

    def add_arguments(self, parser):
        parser.add_argument('--rerun', action='store_true', default=False,
                            help="Rerun OCR on all images")
        parser.add_argument('--since', required=False, help="Only consider images after the given date (date format: YYYY-MM-DD)")
        parser.add_argument('--batch-size', type=int, default=50,
                            help="Number of images loaded and queued at once; results are saved as they arrive")
        parser.add_argument('--workers', type=int, default=4, help="Number of parallel OCR processes")

    def parse_since_argument(self, since):
        if since is None:
            return None
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d")
            return make_aware(since_dt)
        except ValueError:
            logger.error(f"'since' argument {since} has invalid format. Must be YYYY-MM-DD")
            sys.exit(1)

    def get_logger(self):
        handler = logging.StreamHandler(self.stdout)
        logger.addHandler(handler)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        return logger

    def get_images_filtered(self, rerun, since_parsed):
        filters = {}
        if not rerun:
            filters['ocr_timestamp__isnull'] = True
        if since_parsed is not None:
            filters['ocr_timestamp__gte'] = since_parsed
        return ItemImage.objects.filter(**filters)

    def handle(self, *args, rerun=False, since=None, batch_size=50, workers=4, **kwargs):
        self.get_logger()
        since_parsed = self.parse_since_argument(since)
        images = self.get_images_filtered(rerun, since_parsed).order_by("pk")
        total = images.count()
        logger.info(f"Running OCR on {total} images in batches of {batch_size}")
        logger.info("")
        progress = tqdm(total=total)
        last_pk = 0
        with mp.get_context("fork").Pool(workers, initializer=limit_tesseract_threads) as pool:
            while batch := {image.pk: image for image in images.filter(pk__gt=last_pk)[:batch_size]}:
                last_pk = max(batch)
                id_to_path = [(image.pk, image.image.path) for image in batch.values()]
                for image_id, ocr_text in pool.imap(func=run_ocr, iterable=id_to_path):
                    batch[image_id].update_ocr_text(ocr_text)
                    progress.update()
        progress.close()
