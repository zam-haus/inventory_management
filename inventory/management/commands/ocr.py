from django.core.management.base import BaseCommand, CommandError
from inventory.models import ItemImage
from tqdm import tqdm
import multiprocessing as mp
from multiprocessing import Pool
import pytesseract
import logging

def run_ocr(id_with_path):
    image_id, path = id_with_path
    return (image_id, pytesseract.image_to_string(path))

class Command(BaseCommand):
    help = "Runs OCR on item images"

    def add_arguments(self, parser):
        parser.add_argument('--rerun', action='store_true', default=False,
                            help="Rerun OCR on all images")

    def get_logger(self):
        logger = logging.getLogger("ocr")
        logger.handlers.clear()
        handler = logging.StreamHandler(self.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger
        

    def handle(self, *args, rerun=False, **kwargs):
        logger = self.get_logger()
        mp.set_start_method("fork")

        logger.info("Collecting image paths...")
        id_to_path = {image.id : image.image.path
                      for image in ItemImage.objects.all()
                      if image.image and (not image.ocr_text or rerun)}
        logging.info("Done")
        with Pool(4) as pool:
            id_to_ocr_text = dict(list(tqdm(pool.imap(func=run_ocr, iterable=id_to_path.items()), total=len(id_to_path))))
        logging.info("Writing results to database")
        for image_id, ocr_text in tqdm(id_to_ocr_text.items()):
            image_db = ItemImage.objects.get(id=image_id)
            image_db.ocr_text = ocr_text
            image_db.save()
        
