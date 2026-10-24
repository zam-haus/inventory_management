"""Django configuration for the inventory application."""
import os
from pathlib import Path
import json


def parse_bool(value):
    """Parse environment flags using the former strtobool values."""
    value = value.lower()
    if value in ("y", "yes", "t", "true", "on", "1"):
        return True
    if value in ("n", "no", "f", "false", "off", "0"):
        return False
    raise ValueError(f"invalid truth value {value!r}")


def with_scheme(url):
    """Address settings may be given as a bare domain ("inventar.zam.haus"); HTTPS is meant then."""
    url = url.strip()
    return url if not url or "://" in url else f"https://{url}"


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/
STATIC_ROOT = os.path.join(BASE_DIR, "data", "static")
STATIC_URL = "static/"
# Media files (e.g., uploads by users)
MEDIA_ROOT = os.path.join(BASE_DIR, "data", "media")
MEDIA_URL = "media/"
# Static URLs carry ?v=<content hash>, so browsers load changed files at once (inventory/static_versions.py).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "inventory.static_versions.VersionedStaticFilesStorage"},
}


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# For production, overwrite in local_settings.py
# generate using this code:
# import random, string
# "".join(random.choices([c for c in string.printable if c not in "\t\n\r\x0b\x0c], k=64))
SECRET_KEY = os.getenv("SECRET_KEY", None)

# For deployment, set to False in local_settings.py
DEBUG = parse_bool(os.getenv("DEBUG", "false"))
ADMINS = json.loads(os.getenv("ADMINS", "[]"))

# The inventory's main address (also in printed location labels); a bare domain means HTTPS. Every other domain
# name redirects here, keeping path and query (imzam/canonical_host.py); label ID
# resolver hosts redirect to LABEL_ID_RESOLVER_URL instead. Never redirected: IP
# addresses, localhost and *.localhost. CANONICAL_HOST_REDIRECT=false turns it off.
# DEFAULT_DOMAIN is the former name of the variable.
DEFAULT_URL = with_scheme(os.getenv("DEFAULT_URL") or os.getenv("DEFAULT_DOMAIN") or "https://inventar.zam.haus")
CANONICAL_HOST_REDIRECT = parse_bool(os.getenv("CANONICAL_HOST_REDIRECT", "true"))
# Earlier addresses of the inventory, found on old location labels: they redirect like
# every other domain, and scans of their URLs are still recognised.
DOMAIN_ALIASES = [
    with_scheme(url) for url in os.getenv("DOMAIN_ALIASES", "https://inv.zam.haus").split(",") if url.strip()
]

# label IDs: hosts that serve only the QR resolver (they behave like DEFAULT_URL/id/).
# Each must also be in ALLOWED_HOSTS. i.localhost / id.localhost help local testing.
LABEL_ID_RESOLVER_HOSTS = [
    host.strip()
    for host in os.getenv("LABEL_ID_RESOLVER_HOSTS", "i.zam.haus,id.zam.haus,i.localhost,id.localhost").split(",")
    if host.strip()
]
# Where resolver hosts redirect to; defaults to DEFAULT_URL.
LABEL_ID_INVENTORY_BASE = with_scheme(os.getenv("LABEL_ID_INVENTORY_BASE", "")) or None
# The main resolver address: the other resolver hosts redirect there, except label scans,
# which go straight on to the inventory (see imzam/canonical_host.py).
LABEL_ID_RESOLVER_URL = with_scheme(os.getenv("LABEL_ID_RESOLVER_URL", "https://id.zam.haus/"))
# Base URL in the QR codes of label IDs (uppercased for the QR alphanumeric mode). Only
# https://i.zam.haus/ fits QR version 1; longer bases (local testing) make the codes larger.
LABEL_ID_BASE_URL = with_scheme(os.getenv("LABEL_ID_BASE_URL", "https://i.zam.haus/"))
# The name users see for label IDs (UI, labels); code and database say "label ID".
LABEL_ID_NAME = os.getenv("LABEL_ID_NAME", "ZAMid")
# How many label scans and web form entries are kept per label ID (see inventory/label_ids/access.py).
LABEL_ID_ACCESS_KEEP = int(os.getenv("LABEL_ID_ACCESS_KEEP", "5"))

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# https://docs.djangoproject.com/en/4.0/ref/settings/#std:setting-ALLOWED_HOSTS
allowed_hosts = os.getenv("ALLOWED_HOSTS", ".localhost,127.0.0.1,[::1]")
ALLOWED_HOSTS = list(map(str.strip, allowed_hosts.split(",")))

# Application definition

INSTALLED_APPS = [
    "inventory.apps.InventoryConfig",
    "dal",#django-autocomplete-light
    "dal_select2",
    "django.contrib.admin",
    "django.contrib.auth",
    "mozilla_django_oidc",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crispy_forms",
    "crispy_bootstrap5",
    "django_bootstrap5",
    "extra_views",
    "computedfields",
    "accounts",
    "label_printing.apps.LabelPrintingConfig",
    "sorl.thumbnail",
    "django_static_jquery",
]

# Bootstrap is vendored (see its README there) instead of loaded from a CDN, so pages
# work without third parties; update the hashes together with the files.
BOOTSTRAP5 = {
    "css_url": {
        "url": "/static/inventory/vendor/bootstrap/bootstrap.min.css",
        "integrity": "sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB",
    },
    "javascript_url": {
        "url": "/static/inventory/vendor/bootstrap/bootstrap.bundle.min.js",
        "integrity": "sha384-FKyoEForCGlyvwx9Hj09JcYn3nv7wiPVlz7YYwJrWVcXK/BmnVDxM+D2scQbITxI",
    },
}

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Add these settings after INSTALLED_APPS

SELECT2_CACHE_BACKEND = "default"
SELECT2_JS = ''
SELECT2_CSS = ''
SELECT2_I18N_AVAILABLE_LANGUAGES = ['de', 'en']
COMPUTEDFIELDS_ALLOW_RECURSION = True

MIDDLEWARE = [
    # /healthz for healthchecks; first, before host validation and redirects.
    "imzam.health.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Redirects other domains to DEFAULT_URL / LABEL_ID_RESOLVER_URL; before routing by host.
    "imzam.canonical_host.CanonicalHostMiddleware",
    # Routes i.zam.haus / id.zam.haus to the label ID resolver; before CommonMiddleware.
    "inventory.label_ids.middleware.ResolverHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "inventory.actor.CurrentActorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'mozilla_django_oidc.middleware.SessionRefresh',
    'imzam.local_network.LocalNetworkMiddleware',
]

ROOT_URLCONF = "imzam.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'templates'],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.static",
                "django.template.context_processors.media",
                "inventory.favicon.favicon_context",
                "accounts.context_processors.local_network",
                "accounts.context_processors.login",
                "inventory.label_ids.naming.context",
                "inventory.link_scanner.scan_hosts",
            ],
        },
    },
]

WSGI_APPLICATION = "imzam.wsgi.application"

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "django"),
        "USER": os.getenv("POSTGRES_USER", "django"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "password"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}


# ================================================================
# OpenID and Athentication Configuration
# ================================================================

AUTH_USER_MODEL = "accounts.User"

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'accounts.auth.CustomOidcAuthenticationBackend',
)

# Log in through OIDC (SSO)? Unset: yes if OIDC_RP_CLIENT_SECRET is configured, otherwise
# Django's own login (local development, or running without an SSO system).
OIDC_ENABLED = parse_bool(os.environ["OIDC_ENABLED"]) if os.getenv("OIDC_ENABLED") else None

OIDC_RP_CLIENT_ID = os.getenv('OIDC_RP_CLIENT_ID', 'inv.zam.haus')
OIDC_RP_CLIENT_SECRET = os.getenv('OIDC_RP_CLIENT_SECRET')
OIDC_OP_AUTHORIZATION_ENDPOINT = os.getenv(
    'OIDC_OP_AUTHORIZATION_ENDPOINT',
    'https://sso.zam.haus/realms/ZAM/protocol/openid-connect/auth')
OIDC_OP_TOKEN_ENDPOINT = os.getenv(
    'OIDC_OP_TOKEN_ENDPOINT',
    'https://sso.zam.haus/realms/ZAM/protocol/openid-connect/token')
OIDC_OP_USER_ENDPOINT = os.getenv(
    'OIDC_OP_USER_ENDPOINT',
    'https://sso.zam.haus/realms/ZAM/protocol/openid-connect/userinfo')
OIDC_OP_LOGOUT_URL = os.getenv(
    'OIDC_OP_LOGOUT_URL',
    'https://sso.zam.haus/realms/ZAM/protocol/openid-connect/logout?redirect_uri={}')
if OIDC_OP_LOGOUT_URL:
    OIDC_OP_LOGOUT_URL_METHOD = 'accounts.auth.provider_logout'
OIDC_RP_SIGN_ALGO = 'RS256'
OIDC_OP_JWKS_ENDPOINT = os.getenv(
    'OIDC_OP_JWKS_ENDPOINT',
    'https://sso.zam.haus/realms/ZAM/protocol/openid-connect/certs')
LOGIN_REDIRECT_URL = '/'
ALLOW_LOGOUT_GET_METHOD = True
LOGOUT_REDIRECT_URL = '/'
OIDC_CLAIM_REFERENCE_KEY = os.getenv("OIDC_CLAIM_REFERENCE_KEY", 'ldap_id')
OIDC_CLAIM_USERNAME_KEY = os.getenv("OIDC_CLAIM_USERNAME_KEY", 'preferred_username')
LOGIN_URL = '/oidc/authenticate'

OIDC_ADMIN_GROUPS = list(map(
    str.strip,
    os.getenv("OIDC_ADMIN_GROUPS", 'Admin, InventoryAdmin').split(',')))

OIDC_STAFF_GROUPS = list(map(
    str.strip,
    os.getenv("OIDC_ADMIN_GROUPS", 'Admin, InventoryAdmin').split(',')))

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = "de-DE"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True


LANGUAGES = [
    ("en", "English"),
    ("de", "German"),
]

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ================================================================
# Label printing (docs/label-printing.md)
# ================================================================

# Celery broker (e.g. redis://redis:6379/0). Without one, print jobs for network printers run
# right away in the request (development); see below.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {"label_printing.tasks.*": {"queue": "label_printing"}}
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# A job not picked up within this many seconds is not printed any more (the user has moved on).
PRINT_JOB_MAX_AGE = int(os.getenv("PRINT_JOB_MAX_AGE", "120"))
# A job being printed for longer than this without a result counts as failed.
PRINT_JOB_LEASE = int(os.getenv("PRINT_JOB_LEASE", "180"))
# A print agent that has not asked for jobs for this long is offline.
PRINT_AGENT_OFFLINE_AFTER = int(os.getenv("PRINT_AGENT_OFFLINE_AFTER", "30"))
PRINT_MAX_COPIES = int(os.getenv("PRINT_MAX_COPIES", "20"))
# A label asked for while no printer can print it waits this many seconds for one (printer back, tape changed).
PRINT_WAIT_MAX = int(os.getenv("PRINT_WAIT_MAX", "300"))
# Print agents register themselves; at most this many may wait for activation, each with this many printers.
PRINT_AGENT_MAX_PENDING = int(os.getenv("PRINT_AGENT_MAX_PENDING", "20"))
PRINT_AGENT_MAX_PRINTERS = int(os.getenv("PRINT_AGENT_MAX_PRINTERS", "20"))

# Local network: requests from these sources make logged-in users members of LOCAL_GROUP_NAME
# (imzam/local_network.py). Hostnames (all A records), IP addresses, or CIDR networks.
# The ZAM_LOCAL_* variables are the former names and still work.
LOCAL_NETWORK_SOURCES = [
    source.strip()
    for source in (os.getenv("LOCAL_NETWORK_SOURCES") or os.getenv("ZAM_LOCAL_SOURCES") or "das.zam.haus").split(",")
    if source.strip()
]
LOCAL_NETWORK_DNS_CACHE_SECONDS = int(
    os.getenv("LOCAL_NETWORK_DNS_CACHE_SECONDS") or os.getenv("ZAM_LOCAL_DNS_CACHE_SECONDS") or "60")
# Shown next to members' names and in label ID accesses, e.g. "(ZAM)", "at ZAM".
LOCAL_NETWORK_NAME = os.getenv("LOCAL_NETWORK_NAME", "ZAM")
# The locally managed group of members (existing databases have "ZAM-local").
LOCAL_GROUP_NAME = os.getenv("LOCAL_GROUP_NAME", "ZAM-local")


# Overwrite default settings with local_settings.py configuration
if not os.getenv("IGNORE_LOCAL_SETTINGS", False):
    try:
        from .local_settings import *
    except ImportError:
        pass

# No broker: Celery runs tasks at once, in the calling process (unless local_settings decides).
if "CELERY_TASK_ALWAYS_EAGER" not in globals():
    CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL
CELERY_TASK_EAGER_PROPAGATES = True
if not CELERY_BROKER_URL:
    CELERY_BROKER_URL = "memory://localhost/"  # in-process, never used by eager tasks

if OIDC_ENABLED is None:
    OIDC_ENABLED = bool(OIDC_RP_CLIENT_SECRET)
if not OIDC_ENABLED:
    AUTHENTICATION_BACKENDS = tuple(b for b in AUTHENTICATION_BACKENDS if b != 'accounts.auth.CustomOidcAuthenticationBackend')
    MIDDLEWARE = [m for m in MIDDLEWARE if m != 'mozilla_django_oidc.middleware.SessionRefresh']
    LOGIN_URL = 'login'


# ================================================================
# Logging
# ================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'mozilla_django_oidc': {
            'handlers': ['console'],
            'level': 'WARNING'
        },
    },
}
