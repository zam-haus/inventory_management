# Text recognition on photos

The text on item photos (labels, packaging, receipts) is recognized in the background and stored with the photo
(`ItemImage.ocr_text`), so the search finds items by it. New and replaced photos go to the `ocr` worker
(`inventory/tasks.py`); `manage.py ocr` catches up on the rest ([ops/README.md](../ops/README.md)).

## How

`inventory/ocr_util.py`:

1. The photo is turned upright as taken (EXIF orientation) and scaled down to 2000 pixels.
2. EAN barcodes are decoded with zbar at several sizes; codes with a valid check digit (EAN-13, EAN-8, UPC-A)
   become lines `EAN <digits>`, so a scanned or typed EAN finds the item.
3. A text detection model (PP-OCRv3 from the OpenCV model zoo, Apache 2.0) finds the lines of text, also slanted
   or vertical ones.
4. Each line is cut out lying, scaled to 64 pixels height and binarized (light text on dark is inverted). All lines
   are stacked on one white page that Tesseract (`deu+eng`, `--psm 4`) reads in one go, upright and upside down;
   the more confident reading wins.
5. Words with a confidence below 60 and lines that are mostly symbols are dropped.

Tesseract alone, as before, reads the whole photo as a page: textures, edges, holes in perforated panels and barcode
stripes become garbage such as `‘ | ao | { SE BITE nf}`, and small or turned text is lost.

The model file is downloaded into the Docker image (`Dockerfile`, checksum pinned) and found through
`OCR_TEXT_DETECTION_MODEL`. Without it (development), Tesseract reads whole photos with Sauvola binarization and the
same filter, with a warning in the log; without the zbar library, OpenCV decodes barcodes, finding fewer.

## Tuning

The settings were tuned on 100 random photos whose old text was garbage (70) or empty (30), against the words a
person can read on them, plus 30 photos with good text as a check. With the same Tesseract version:

| | readable words found | output words not on the photo | useful results |
|---|---|---|---|
| Before (whole photo) | 3% | 93% | 23% |
| Now | 46% | 34% | 69% |
| Check set before → now | 77% → 91% | 18% → 9% | 90% → 97% |

"Useful": at least 40% of the readable words and at most 50% garbage; for photos without legible text (a third of
the sample), an (almost) empty result. EANs: 31 of 43 readable codes are decoded, none wrong. The largest gains came
from the text line detection; EXIF orientation, the confidence filter and binarization on their own got the useful
results only to 46%.

## Cost

About 3 seconds per photo on one core instead of 1, and about 500 MB memory per process (model and OpenCV) instead
of 250 MB. OpenCV and Tesseract use one thread each. On the production server (4 cores, 8 GB),
`ops/manage.sh ocr --rerun --workers 2` recognizes all photos again in roughly 7 hours, leaving two cores to the app;
it saves each batch and works on the photos recognized longest ago first, so it can be stopped and continued with
`--rerun --ocr-before <date it was started>`.
