"""
NexChat Django settings.

Environment is selected via the DJANGO_ENV variable:
  DJANGO_ENV=dev   (default) — SQLite + InMemoryChannelLayer, relaxed security
  DJANGO_ENV=prod             — MySQL   + Redis, hardened security settings

Logs are always written to files (logs/ directory next to manage.py).
Log level is DEBUG in dev and WARNING in prod.
"""

from pathlib import Path
from decouple import config
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

DJANGO_ENV = config("DJANGO_ENV", default="dev")
IS_PROD = DJANGO_ENV == "prod"

# Ensure the logs directory exists at startup
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Core
SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-secret-change-in-production")

DEBUG = config("DEBUG", default=not IS_PROD, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1" if IS_PROD else "*",
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "channels",
    # local
    "accounts",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves static files via uvicorn
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nexchat.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ASGI — Daphne serves both HTTP and WebSocket
ASGI_APPLICATION = "nexchat.asgi.application"
WSGI_APPLICATION = "nexchat.wsgi.application"

# Database
if IS_PROD:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("MYSQL_DB", default="nexchat"),
            "USER": config("MYSQL_USER", default="nexchat"),
            "PASSWORD": config("MYSQL_PASSWORD", default="nexchat"),
            "HOST": config("MYSQL_HOST", default="db"),
            "PORT": config("MYSQL_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Channel layer
# prod → Redis (supports multiple workers / horizontal scaling)
# dev  → InMemory (zero setup, single-process only)
if IS_PROD:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(config("REDIS_HOST", default="redis"), 6379)],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

# Security (prod only)
if IS_PROD:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000          # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"

# CORS
# prod → only allow explicitly listed frontend origins
# dev  → allow all (handled by ALLOWED_HOSTS=*)
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="",
).split(",") if IS_PROD else []

# Auth
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Logging
# Always writes to rotating log files.
# Dev: DEBUG level  |  Prod: WARNING level
_LOG_LEVEL = "WARNING" if IS_PROD else "DEBUG"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {module}:{lineno} — {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "django_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "django.log"),
            "maxBytes": 10 * 1024 * 1024,   # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "chat_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "chat.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["django_file", "console"],
        "level": _LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["django_file", "console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["django_file", "console"],
            "level": "WARNING",
            "propagate": False,
        },
        "channels": {
            "handlers": ["chat_file", "console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "chat": {
            "handlers": ["chat_file", "console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
        "accounts": {
            "handlers": ["django_file", "console"],
            "level": _LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Static / Internationalisation
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise — serves static files through uvicorn without a separate web server.
# In dev: WHITENOISE_USE_FINDERS lets it serve directly from STATICFILES_DIRS
#         without needing to run collectstatic first.
# In prod: serves from STATIC_ROOT (populated by collectstatic in the Docker CMD).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_USE_FINDERS = not IS_PROD  # dev only: serve from STATICFILES_DIRS directly

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Pagination
MESSAGE_PAGE_SIZE = config("MESSAGE_PAGE_SIZE", default=50, cast=int)
