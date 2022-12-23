import logging
import multiprocessing as mp
import sys
from datetime import datetime
from multiprocessing import Pool

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware
from tqdm import tqdm

from inventory.models import ItemImage
from inventory.ocr_util import ocr_on_image_path

logger = logging.getLogger("ocr")
logger.handlers.clear()
logger.setLevel(logging.INFO)

def run_ocr(id_with_path):
    image_id, path = id_with_path
    return (image_id, ocr_on_image_path(path))

class Command(BaseCommand):
    help = "Runs OCR on item images"

    def add_arguments(self, parser):
        parser.add_argument('--rerun', action='store_true', default=False,
                            help="Rerun OCR on all images")
        parser.add_argument('--since', required=False, help="Only consider images after the given date (date format: YYYY-MM-DD)")

    def parse_since_argument(self, since):
        if since is None:
            return None
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d")
            return make_aware(since_dt)
        except ValueError:
            logger.error(f"'since' argument {since} has invalid format. Must be YYYY-MM-DD")
            sys.exit(1)

    def configure_logger(self):
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

    def handle(self, *args, rerun=False, since=None,  **kwargs):
        self.configure_logger()
        since_parsed = self.parse_since_argument(since)
        mp.set_start_method("fork")
        logger.info("Collecting image paths...")
        id_to_path = {image.id : image.image.path for image in self.get_images_filtered(rerun, since_parsed)}
        logger.info(f"Running OCR on {len(id_to_path)} images")
        logger.info("")
        with Pool(4) as pool:
            id_to_ocr_text = dict(list(tqdm(pool.imap(func=run_ocr, iterable=id_to_path.items()), total=len(id_to_path))))
        logging.info("Writing results to database")
        for image_id, ocr_text in tqdm(id_to_ocr_text.items()):
            image_db = ItemImage.objects.get(id=image_id)
            image_db.update_ocr_text(ocr_text)
        
