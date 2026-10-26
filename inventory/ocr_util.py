"""Text recognition on photos (docs/ocr.md). Every Django process imports this through the models; OpenCV, zbar and
the detection model (inventory/text_recognition.py, about 0.4 GB per process) are loaded only on the first photo,
in the ocr worker and manage.py ocr."""


def ocr_on_image_path(image_path):
    """Text and EAN codes on the photo, one line each; empty if there is none."""
    from . import text_recognition
    return text_recognition.recognize(image_path)
