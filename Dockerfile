# syntax=docker/dockerfile:1
FROM docker.io/library/python:3.14
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y \
     gettext tesseract-ocr tesseract-ocr-deu libzbar0 \
     && rm -rf /var/lib/apt/lists/*
# Maps (docs/maps.md) are optional: build with MAPS=1 for GeoDjango's libraries (GDAL, GEOS, PROJ) and poppler,
# which renders PDF floor plans (docker-compose.maps.yml does that).
ARG MAPS=0
RUN if [ "$MAPS" = "1" ]; then apt-get update && apt-get install -y \
     binutils gdal-bin libproj-dev poppler-utils \
     && rm -rf /var/lib/apt/lists/*; fi
# Finds the lines of text on photos for OCR (inventory/text_recognition.py):
# PP-OCRv3 from the OpenCV model zoo, Apache 2.0
RUN mkdir -p /opt/ocr && curl -fsSL -o /opt/ocr/text_detection_ppocrv3.onnx \
     https://huggingface.co/opencv/text_detection_ppocr/resolve/c299e81aedeaf5d4f741fccccea491fb32db005f/text_detection_en_ppocrv3_2023may.onnx \
     && echo "03f550c6b406fda8bf54bd8327815f6c7e2edd98cea02348c93d879254366587  /opt/ocr/text_detection_ppocrv3.onnx" | sha256sum -c -
WORKDIR /code
COPY requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt
# The code is part of the image, so code changes need a rebuild (ops/update.sh).
# What stays out: .dockerignore
COPY . /code/
RUN ./manage.py compilemessages
CMD ["./web-entrypoint.sh"]
