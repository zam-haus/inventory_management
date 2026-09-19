import re

import pytesseract

def ocr_on_image_path(image_path):
    """Extract German/English text and normalize excess whitespace."""
    ocr_raw = pytesseract.image_to_string(image_path, lang='deu+eng')
    # remove multiple blank lines and long spaces
    return re.sub(
            r'[ \t\r\f\v]+\n[ \n\t\r\f\v]+', '\n',
            re.sub(r'[ \t\r\f\v]+', ' ', ocr_raw.strip()))
