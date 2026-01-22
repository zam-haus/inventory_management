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

OIDC_RP_CLIENT_ID = ''
OIDC_RP_CLIENT_SECRET = ''

# ================================================================
# Celery config
# ================================================================
# Setting CELERY_TASK_ALWAYS_EAGER executes all celery tasks locally by blocking until the task returns. Set this to False
# if you have a local running instance of redis and use the command 'python manage.py celery_worker run' to start the celery worker
CELERY_TASK_ALWAYS_EAGER = True