"""Django settings for the standalone ZORY spatial-planning runner.

This `project` package is only the local-dev runner. The actual functionality is the
self-contained `spatial_planning` Django app (views + urls + the framework-agnostic
domain code under spatial_planning/services, /models, /handlers, /config, /errors).
When merged into the main Zory_ai repo, this `project` package is discarded and
`spatial_planning` is added to that project's INSTALLED_APPS instead.

No django.contrib.* (admin/auth/sessions): the app has no ORM models and no auth, so
no database or migrations are required.
"""

from pathlib import Path

from spatial_planning.config import get_settings

_s = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent

# Dev-only. Not security-sensitive: no sessions/auth/admin are enabled.
SECRET_KEY = "dev-only-not-secret-spatial-planning"
DEBUG = _s.debug
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "spatial_planning",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "spatial_planning.middleware.BootstrapAndLoggingMiddleware",
]

ROOT_URLCONF = "project.urls"
WSGI_APPLICATION = "project.wsgi.application"

# Django requires DATABASES defined even though we never touch the ORM (designs/orders
# use the app's own stdlib sqlite via spatial_planning.services.persistence.db).
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# CORS: origins from the app config, credentials allowed (mirrors the prior setup).
CORS_ALLOWED_ORIGINS = list(_s.cors_origins)
CORS_ALLOW_CREDENTIALS = True

# Routes have no trailing slash; do not 301-redirect to a slashed variant.
APPEND_SLASH = False

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "spatial_planning.exception_handler.zory_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"zory": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "zory"}},
    "loggers": {"zory": {"handlers": ["console"], "level": "INFO"}},
}
