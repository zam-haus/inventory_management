# Example local_settings.py for development usage
# INSECURE, DO NOT USE IN PRODUCTION!
from pathlib import Path

DEBUG = True
# Any host name or address reaches the dev server (phones in the LAN, i.localhost for label IDs, …),
# and none is redirected to the main domain (DEFAULT_URL).
ALLOWED_HOSTS = ['*']
CANONICAL_HOST_REDIRECT = False

# Label printing: without CELERY_BROKER_URL jobs for network printers print right away in the
# request. Fake printers to print on: python -m label_printing.simulator (docs/label-printing.md).

# Log in with Django's own accounts (python manage.py createsuperuser). To test the SSO
# login locally, configure the OIDC_* settings and set OIDC_ENABLED = True.
OIDC_ENABLED = False

# Label IDs locally: QR codes point at the local resolver (a larger QR version than in
# production), and the resolver redirects back to this server.
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

# Mails (error mails, "Report a problem") are printed in the runserver console instead of sent.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Someone to send problem reports to, so the menu offers "Report a problem" (docs/problem-reports.md).
PROBLEM_REPORT_EMAILS = ["admins@localhost"]
