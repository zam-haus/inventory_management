# Example local_settings.py for development usage
# INSECURE, DO NOT USE IN PRODUCTION!
from pathlib import Path

DEBUG = True
TEMPLATE_DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1']

# If label printing is to be tested:
#MQTT_PASSWORD_AUTH = dict(
#    username="im.zam.haus-django",
#    password='ASK SOME WHO KNOWS (only needed for label printing)')
# Alternativly use
#MQTT_PRINTER_TOPIC='public/'
# to publish in an unrestricted topic.

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

OIDC_RP_CLIENT_SECRET = ''
