# syntax=docker/dockerfile:1
FROM docker.io/library/python:3.14
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y \
     gettext tesseract-ocr tesseract-ocr-deu \
     && rm -rf /var/lib/apt/lists/*
WORKDIR /code
COPY requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt
# The code is part of the image, so code changes need a rebuild (ops/update.sh).
# What stays out: .dockerignore
COPY . /code/
RUN ./manage.py compilemessages
CMD ["./web-entrypoint.sh"]
