"""
Base settings to build other settings files upon.
"""
from pathlib import Path

import environ
from django.conf.locale import LANG_INFO
from multisite import SiteID

ROOT_DIR = Path(__file__).parents[2]
# portal/)
APPS_DIR = ROOT_DIR / "portal"
env = environ.Env()

# Sentry:
SENTRY_DSN = env("SENTRY_DSN", default=None)
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        send_default_pii=True,
        traces_sample_rate=1.0,
    )


READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(ROOT_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
# TIME_ZONE = "UTC+12"
TIME_ZONE = "Pacific/Auckland"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en"
gettext = lambda s: s  # noqa: E731
LANGUAGES = [
    ("en", gettext("English")),
    ("mi", gettext("Maori")),
]
MODELTRANSLATION_DEFAULT_LANGUAGE = "en"
MODELTRANSLATION_LANGUAGES = ["en", "mi"]
LANG_INFO.update(
    {
        "mi": {
            "bidi": False,
            "code": "mi",
            "name": "Maori",
            "name_local": "Māori",
        },
        # "en-nz": {
        #     "bidi": False,
        #     "code": "en-nz",
        #     "name": "New Zealand English",
        #     "name_local": "New Zealand English",
        # },
    }
)

# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
#  SITE_ID = 1
SITE_ID = SiteID(default=1)
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-l10n
USE_L10N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(ROOT_DIR / "locale")]

# https://django-taggit.readthedocs.io/en/latest/getting_started.html
TAGGIT_CASE_INSENSITIVE = True

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"  # 32-bit
DATABASES = {"default": env.db("DATABASE_URL", default="postgres:///portal")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    # "portal.apps.SitesConfig",
    "multisite",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # NB: has to be added before admin
    "modeltranslation",
    "dal",
    "dal_select2",
    # "dal_queryset_sequence",
    # https://github.com/maykinmedia/django-admin-index
    # "django_admin_index",
    # "ordered_model",
    # "grappelli",
    "django.contrib.admin",
    "django.forms",
    "django.contrib.flatpages",
    # "django_mail_admin",
]
THIRD_PARTY_APPS = [
    "captcha",
    "simple_history",
    # "background_task",
    "crispy_forms",
    # "crispy_bootstrap4",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.orcid",
    # "allauth.socialaccount.providers.rapidconnect",
    "rapidconnect",
    "rest_framework",
    "rest_framework.authtoken",
    "django_tables2",
    "import_export",
    "django_select2",
    "private_storage",
    "django_fsm_log",
    "fsm_admin",
    "django_fsm",
    "django_summernote",
    "django_filters",
    "bootstrap4",
    "explorer",
    # "dynamic_breadcrumbs",
    "django_bootstrap_breadcrumbs",
    # "taggit",
    "admin_ordering",
]

# workaround for https://github.com/shestera/django-multisite/issues/9
SILENCED_SYSTEM_CHECKS = ["sites.E101"]  # Check to ensure SITE_ID is an int - ours is an object

# EXPLORER_CONNECTIONS = {"Default": "readonly"}
# EXPLORER_DEFAULT_CONNECTION = "readonly"
EXPLORER_CONNECTIONS = {"Default": "default"}
EXPLORER_DEFAULT_CONNECTION = "default"

LOCAL_APPS = [
    "portal",
    "users.apps.UsersConfig",
    # Your stuff: custom apps go here
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "portal.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
# LOGIN_REDIRECT_URL = "users:redirect"
LOGIN_REDIRECT_URL = "home"
# ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS = False
ACCOUNT_LOGOUT_ON_GET = True
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"
# LOGOUT_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "/accounts/login/?logout=1"
ACCOUNT_LOGOUT_REDIRECT_URL = LOGOUT_REDIRECT_URL
HTTP_BASIC_AUTH_URL = "/auth"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "multisite.middleware.CookieDomainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "multisite.middleware.DynamicSiteMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # "django.contrib.flatpages.middleware.FlatpageFallbackMiddleware",
    "portal.middleware.FlatpageFallbackMiddleware",
]


# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(ROOT_DIR / "static"), str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# Protected storage:
PRIVATE_STORAGE_ROOT = str(ROOT_DIR / "private-media")
PRIVATE_STORAGE_AUTH_FUNCTION = "private_storage.permissions.allow_authenticated"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#template-dirs
        "DIRS": [str(APPS_DIR / "templates")],
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-loaders
            # https://docs.djangoproject.com/en/dev/ref/templates/api/#loader-types
            "loaders": [
                "multisite.template.loaders.filesystem.Loader",
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                # "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                # "dynamic_breadcrumbs.context_processors.breadcrumbs",
                # "django.template.context_processors.request",
                "portal.context_processors.portal_context",
            ],
        },
    },
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [str(APPS_DIR / "jinja2")],
        "APP_DIRS": True,
        "OPTIONS": {
            "environment": "jinja2_env.environment",
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
# CRISPY_ALLOWED_TEMPLATE_PACKS = ["bootstrap4",]
CRISPY_TEMPLATE_PACK = "bootstrap4"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SAMESITE = "None"
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-browser-xss-filter
SECURE_BROWSER_XSS_FILTER = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
# X_FRAME_OPTIONS = "DENY"
X_FRAME_OPTIONS = "SAMEORIGIN"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5
EMAIL_HOST = "smtp.gmail.com"
EMAIL_HOST_USER = "nad2000@gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX", default="[Prime Minister's Science Prizes]"
)

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("Royal Society of New Zealand Te Apārangi", "pmspp001@mailinator.com")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s " "%(process)d %(thread)d %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}


# django-allauth
# ------------------------------------------------------------------------------
SOCIALACCOUNT_LOGIN_ON_GET = True
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ACCOUNT_AUTHENTICATION_METHOD = "username"
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_EMAIL_REQUIRED = True
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://django-allauth.readthedocs.io/en/latest/configuration.html
ACCOUNT_ADAPTER = "users.adapters.AccountAdapter"
# https://django-allauth.readthedocs.io/en/latest/configuration.html
SOCIALACCOUNT_ADAPTER = "users.adapters.SocialAccountAdapter"
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
# django-compressor
# ------------------------------------------------------------------------------
# https://django-compressor.readthedocs.io/en/latest/quickstart/#installation
INSTALLED_APPS += ["compressor"]
STATICFILES_FINDERS += ["compressor.finders.CompressorFinder"]
# django-reset-framework
# -------------------------------------------------------------------------------
# django-rest-framework - https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}
# Your stuff...
# ------------------------------------------------------------------------------

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
            "openid",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
    },
    "orcid": {
        "BASE_DOMAIN": "sandbox.orcid.org",
        "MEMBER_API": False,
    },
    "rapidconnect": {
        "BASE_URL": "https://rapidconnect.staging.tuakiri.ac.nz/jwt/authnrequest/research/",
    },
}
# https://github.com/summernote/django-summernote
SUMMERNOTE_THEME = "bs4"
# SUMMERNOTE_CONFIG = {"iframe": False}
SUMMERNOTE_CONFIG = {"iframe": True}
IMPORT_EXPORT_USE_TRANSACTIONS = True
IMPORT_EXPORT_SKIP_ADMIN_LOG = True

ORCID_BASE_URL = "https://orcid.org/"
ORCID_API_BASE = "https://pub.orcid.org/v3.0/"

RAPIDCONNECT_LOGOUT = "https://rapidconnect.tuakiri.ac.nz/logout"

# DATE_FORMAT = "Y-m-d"
DATE_FORMAT = "d-m-Y"
TIME_FORMAT = "H:M"
DATETIME_FORMAT = f"{DATE_FORMAT} {TIME_FORMAT}"

# FSM_ADMIN_FORCE_PERMIT = True
# Captcha settings you will need to create new captcha app here https://www.google.com/recaptcha/admin/
# Make suer RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY are set
RECAPTCHA_USE_SSL = True
ACCOUNT_FORMS = {
    "signup": "users.forms.UserSignupForm",
}

DATA_UPLOAD_MAX_NUMBER_FIELDS = 4000

# LimeSurvey API
## LIMESURVEY_SERVER_URL = "<URL>"
## LIMESURVEY_API_URL = "<URL>"
## LIMESURVEY_API_USERNAME = "<API username>"
## LIMESURVEY_API_PASSWORD = "<API username password>"
