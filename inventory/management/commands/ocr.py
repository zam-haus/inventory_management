from django.core.management.base import BaseCommand, CommandError
from inventory.models import ItemImage
from inventory.ocr_util import ocr_on_image_path
from tqdm import tqdm
import multiprocessing as mp
from multiprocessing import Pool
import logging

def run_ocr(id_with_path):
    image_id, path = id_with_path
    return (image_id, ocr_on_image_path(path))

class Command(BaseCommand):
    help = "Runs OCR on item images"

    def get_logger(self):
        logger = logging.getLogger("ocr")
        logger.handlers.clear()
        handler = logging.StreamHandler(self.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger
        
    def get_images_filtered(self):
        # Only return images which have not been processed by OCR yet
        return ItemImage.objects.filter(ocr_timestamp__isnull=True)

    def handle(self, *args, **kwargs):
        logger = self.get_logger()
        mp.set_start_method("fork")

        logger.info("Collecting image paths...")
        id_to_path = {image.id : image.image.path for image in self.get_images_filtered()}
        logger.info(f"Running OCR on {len(id_to_path)} images")
        logger.info("")
        with Pool(4) as pool:
            id_to_ocr_text = dict(list(tqdm(pool.imap(func=run_ocr, iterable=id_to_path.items()), total=len(id_to_path))))
        logging.info("Writing results to database")
        for image_id, ocr_text in tqdm(id_to_ocr_text.items()):
            image_db = ItemImage.objects.get(id=image_id)
            image_db.update_ocr_text(ocr_text)
        
