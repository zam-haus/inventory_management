# Example local_settings.py for development usage
# INSECURE, DO NOT USE IN PRODUCTION!
from pathlib import Path

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1']

# If label printing is to be tested:
#MQTT_PASSWORD_AUTH = dict(
#    username="im.zam.haus-django",
#    password='ASK SOME WHO KNOWS (only needed for label printing)')
# Alternativly use
#MQTT_PRINTER_TOPIC='public/'
# to publish in an unrestricted topic.

# Log in with Django's own accounts (python manage.py createsuperuser). To test the SSO
# login locally, configure the OIDC_* settings and set OIDC_ENABLED = True.
OIDC_ENABLED = False

# Label IDs locally: QR codes point at the local resolver (a larger QR version than in
# production), and the resolver redirects back to this server.
ALLOWED_HOSTS += ['i.localhost', 'id.localhost']
LABEL_ID_BASE_URL = 'http://i.localhost:8000/'
LABEL_ID_INVENTORY_BASE = 'http://localhost:8000'

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

OIDC_RP_CLIENT_ID = ''
OIDC_RP_CLIENT_SECRET = ''
