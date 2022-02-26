# syntax=docker/dockerfile:1
FROM python:3
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /code
COPY requirements.txt /code/
RUN pip install -r requirements.txt
RUN apt-get update && apt-get install -y \
     gettext
COPY manage.py imzam inventory web-entrypoint.sh /code/
CMD ["./web-entrypoint.sh"]