import pytesseract
import re

def ocr_on_image_path(image_path):
    """Runs pytesseract OCR on the given with additional postprocessing

    Args:
        image_path (str): Path to the image file
    """
    ocr_raw = pytesseract.image_to_string(image_path, lang='deu+eng')
    # clean up ocr_raw
    # remove multiple blank lines and long spaces
    ocr_processed = re.sub(
            r'[ \t\r\f\v]+\n[ \n\t\r\f\v]+', '\n',
            re.sub(r'[ \t\r\f\v]+', ' ', ocr_raw.strip()))
    return ocr_processed