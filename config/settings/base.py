"""
Base settings to build other settings files upon.
"""

from pathlib import Path

import environ
from django.conf.locale import LANG_INFO
from multisite import SiteID
from simple_history.models import HistoricalChanges
from django.contrib.admin import RelatedOnlyFieldListFilter

ROOT_DIR = Path(__file__).parents[2]
# portal/)
APPS_DIR = ROOT_DIR / "portal"
EXPORTED_DIR = ROOT_DIR / "exported"
GEOIP_PATH = ROOT_DIR / "GeoIP2"
env = environ.Env()

ENV = env("ENV", default="local")

# Sentry:
SENTRY_DSN = env("SENTRY_DSN", default=None)
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(
                cache_spans=True,
            )
        ],
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
SITE_ID = SiteID(default=0)
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-l10n
USE_L10N = False
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
# USE_TZ = True
USE_TZ = False
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

# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = [
    # "django_user_agents",
    # "tracking_analyzer",
    "portal.apps.PortalConfig",
    "users.apps.UsersConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "multisite",
    # "file_resubmit",
    # "redirects",
    "django.contrib.redirects",
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
    "admin_interface",
    "colorfield",
    "django.contrib.admin",
    "django.forms",
    "django.contrib.flatpages",
    "reversion",
    "reversion_compare",
    ## "dbtemplates",
    # "django_mail_admin",
    "captcha",
    "simple_history",
    # "background_task",
    "crispy_forms",
    "crispy_bootstrap4",
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
    "django_fsm",
    "django_fsm_log",
    "fsm_admin",
    "django_summernote",
    "tinymce",
    "django_filters",
    "bootstrap4",
    "explorer",
    # "dynamic_breadcrumbs",
    "django_bootstrap_breadcrumbs",
    "taggit",
    "admin_ordering",
    "easyaudit",
    # "dalf",
    # "autocompletefilter",
    "django_q",
    "constance",
]

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"
# CONSTANCE_DATABASE_CACHE_BACKEND = "default"
CONSTANCE_CONFIG = {
    "DEFAULT_CV_TEMPLATE_URL": (
        "https://www.royalsociety.org.nz/assets/NZ-RST-CV-Template.docx",
        "NZ RST CV Template URL.",
        str,
    ),
    "CHILD_PROTECTION_POLICY_URL": (
        "https://www.royalsociety.org.nz/who-we-are/our-rules-and-codes/policy-on-child-protection/child-protection-policy",
        "Child Protection Policy URL.",
        str,
    ),
}

Q_CLUSTER = {
    "name": "DjangORM",
    "retry": 120,  ## 60
    "workers": 1,
    "timeout": 90,
    "bulk": 10,
    "queue_limit": 500,
    "sync": False if ENV == "prod" else DEBUG,
    "orm": "default",
}
# TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
TASKS = {"default": {"BACKEND": "portal.tasks.Q2Backend"}}

# EXPLORER_CONNECTIONS = {"Default": "readonly"}
# EXPLORER_DEFAULT_CONNECTION = "readonly"
EXPLORER_CONNECTIONS = {"Default": "default"}
EXPLORER_DEFAULT_CONNECTION = "default"
EXPLORER_DATA_EXPORTERS = [
    ("csv", "explorer.exporters.CSVExporter"),
    ("excel", "explorer.exporters.ExcelExporter"),
    ("json", "explorer.exporters.JSONExporter"),
]
# EXPLORER_TRANSFORMS = [
#     ('user', '<a href="/users/{0}/profile" target="_blank">{0}</a>')
# ]
# EXPLORER_PERMISSION_VIEW = lambda r: r.user.is_staff or r.user.is_site_staff
# EXPLORER_PERMISSION_CHANGE = lambda r: r.user.is_staff or r.user.is_site_staff
# EXPLORER_PERMISSION_CONNECTIONS = lambda r: r.user.is_staff or r.user.is_site_staff
### EXPLORER_CHARTS_ENABLED = True
EXPLORER_DB_CONNECTIONS_ENABLED = True
EXPLORER_USER_UPLOADS_ENABLED = True

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
    "django.contrib.redirects.middleware.RedirectFallbackMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "multisite.middleware.DynamicSiteMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # "django.contrib.flatpages.middleware.FlatpageFallbackMiddleware",
    "portal.middleware.PortalMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "easyaudit.middleware.easyaudit.EasyAuditMiddleware",
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
# PRIVATE_STORAGE_CLASS = "common.models.ArchivalStorage"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#template-dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-loaders
            # https://docs.djangoproject.com/en/dev/ref/templates/api/#loader-types
            "loaders": [
                (
                    # "django.template.loaders.cached.Loader",
                    "portal.template.Loader",
                    [
                        # "multisite.template.loaders.filesystem.Loader",
                        "portal.template.MultisiteLoader",
                        "apptemplates.Loader",
                        "django.template.loaders.app_directories.Loader",
                        "django.template.loaders.filesystem.Loader",
                        # "dbtemplates.loader.Loader",
                    ],
                )
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
                "portal.views.portal_context",
            ],
            "debug": DEBUG,
        },
    },
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [str(APPS_DIR / "jinja2")],
        "APP_DIRS": True,
        "OPTIONS": {
            "environment": "jinja2_env.environment",
            "extensions": ["jinja2.ext.i18n"],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"
# FORMS_URLFIELD_ASSUME_HTTPS = True

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"
CRISPY_TEMPLATE_PACK = "bootstrap4"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
# FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_NAME = "portal_sessionid"
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
### CSRF_COOKIE_HTTPONLY = True
# CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "None"
CSRF_FAILURE_VIEW = "portal.views.csrf_failure"
SESSION_COOKIE_SAMESITE = "None"
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-browser-xss-filter
SECURE_BROWSER_XSS_FILTER = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
# X_FRAME_OPTIONS = "DENY"
X_FRAME_OPTIONS = "SAMEORIGIN"

# workaround for https://github.com/shestera/django-multisite/issues/9
# SILENCED_SYSTEM_CHECKS = ["sites.E101"]  # Check to ensure SITE_ID is an int - ours is an object
SILENCED_SYSTEM_CHECKS = ["security.W019", "sites.E101", "captcha.recaptcha_test_key_error"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
# # https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5
# EMAIL_HOST = "smtp.gmail.com"
# EMAIL_HOST_USER = "nad2000@gmail.com"
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
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
        },
        "coloured": {
            "()": "coloredlogs.ColoredFormatter",
            "format": "%(asctime)s %(levelname)s [%(name)s:%(lineno)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "console_coloured": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "coloured",
        },
    },
    "loggers": {
        "django-q": {
            # "handlers": ["console", 'q_file'],
            "handlers": ["console_coloured"],
            "level": "DEBUG",
            "propagate": False,  # Important: Stop propagation to root
        },
        "qcluster": {
            # "handlers": ["console", 'q_file'],
            "handlers": ["console_coloured"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
    # "root": {"level": "INFO", "handlers": ["console"]},
    # "root": {"level": "WARNING", "handlers": ["console"]},
}


# django-allauth
# ------------------------------------------------------------------------------
SOCIALACCOUNT_LOGIN_ON_GET = True
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ACCOUNT_AUTHENTICATION_METHOD = "username"
ACCOUNT_LOGIN_METHODS = {"username", "email"}
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
# https://django-allauth.readthedocs.io/en/latest/configuration.html
# ACCOUNT_EMAIL_REQUIRED = True
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

ALLAUTH_SITES_ENABLED = True
# SOCIALACCOUNT_SITES_ENABLED = True
SOCIALACCOUNT_STORE_TOKENS = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_EMAIL_VERIFICATION = False
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
        # "MEMBER_API": True,
    },
    "rapidconnect": {
        "BASE_URL": "https://rapidconnect.staging.tuakiri.ac.nz/jwt/authnrequest/research/",
        "SITES_ENABLED": True,
    },
}
# https://github.com/summernote/django-summernote
SUMMERNOTE_THEME = "bs4"
# SUMMERNOTE_CONFIG = {"iframe": False}
SUMMERNOTE_CONFIG = {
    # "iframe": True,
    "summernote": {
        # "width": "100%",
        # "airMode": True,
        "disable_attachment": False,
        "fontNames": ["Arial", "Arial Black", "Comic Sans MS", "Courier New", "Merriweather"],
        "fontName": "Arial",
        "fontSize": 10,
        # "addDefaultFonts": True,
        "lang": None,
        # "toolbar": [
        #     # [groupName, [list of button]]
        #     ["style", ["bold", "italic", "underline", "clear"]],
        #     ["font", ["Arial", "Arial Black", "Comic Sans MS", "Courier New", "Merriweather"]],
        #     ["fontsize", ["8", "10", "11", "12", "14", "16", "18", "24", "36"]],
        #     # ['color', ['color']],
        #     ["para", ["ul", "ol", "paragraph"]],
        #     # ['height', ['height']]
        # ],
    },
    "js": ("/static/js/summernote_set_font.js",),
}
IMPORT_EXPORT_USE_TRANSACTIONS = True
IMPORT_EXPORT_SKIP_ADMIN_LOG = True

ORCID_BASE_URL = "https://orcid.org/"
ORCID_API_BASE = "https://pub.orcid.org/v3.0/"

RAPIDCONNECT_LOGOUT = "https://rapidconnect.tuakiri.ac.nz/logout"

# DATE_FORMAT = "Y-m-d"
DATE_FORMAT = "d-m-Y"
TIME_FORMAT = "H:i"
DATETIME_FORMAT = f"{DATE_FORMAT} {TIME_FORMAT}"
SHORT_DATETIME_FORMAT = DATETIME_FORMAT
SHORT_DATE_FORMAT = DATE_FORMAT

# FSM_ADMIN_FORCE_PERMIT = True
# Captcha settings you will need to create new captcha app here https://www.google.com/recaptcha/admin/
# Make suer RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY are set
RECAPTCHA_USE_SSL = True
ACCOUNT_FORMS = {
    "signup": "users.forms.UserSignupForm",
}

DATA_UPLOAD_MAX_NUMBER_FIELDS = 4000
SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD = True

# LimeSurvey API
## LIMESURVEY_SERVER_URL = "<URL>"
## LIMESURVEY_API_URL = "<URL>"
## LIMESURVEY_API_USERNAME = "<API username>"
## LIMESURVEY_API_PASSWORD = "<API username password>"

DJANGO_TABLES2_TABLE_ATTRS = {"class": "table table-striped table-bordered"}
DJANGO_TABLES2_TEMPLATE = "django_tables2/bootstrap4-responsive.html"
# DJANGO_EASY_AUDIT_WATCH_MODEL_EVENTS = False
DJANGO_EASY_AUDIT_UNREGISTERED_CLASSES_EXTRA = [
    "explorer.Query",
    "explorer.QueryLog",
    "explorer.QueryFavorite",
    # "explorer.ExplorerValue",
]
DJANGO_EASY_AUDIT_UNREGISTERED_URLS_DEFAULT = [
    r"^/admin/",
    r"^/static/",
    r"^/favicon.ico$",
    "^/webmanifest",
    "^/summernote",
    "^/status",
    "^/autocomplete",
]
DJANGO_EASY_AUDIT_CRUD_EVENT_LIST_FILTER = [
    "event_type",
    ("content_type", RelatedOnlyFieldListFilter),
    ("user", RelatedOnlyFieldListFilter),
    # ("user", AutocompleteListFilter),
    "datetime",
]
DJANGO_EASY_AUDIT_LOGIN_EVENT_LIST_FILTER = [
    "login_type",
    ("user", RelatedOnlyFieldListFilter),
    "datetime",
]
DJANGO_EASY_AUDIT_REQUEST_EVENT_LIST_FILTER = [
    "method",
    ("user", RelatedOnlyFieldListFilter),
    "datetime",
]


SELECT2_THEME = "bootstrap4"


def crud_difference_callbacks(model, *args, **kwargs):
    return not isinstance(model, HistoricalChanges)


ADD_REVERSION_ADMIN = True
DJANGO_EASY_AUDIT_CRUD_DIFFERENCE_CALLBACKS = [crud_difference_callbacks]
DBTEMPLATES_USE_REVERSION = True
DBTEMPLATES_USE_REVERSION_COMPARE = True
DBTEMPLATES_ADD_DEFAULT_SITE = True
# DBTEMPLATES_AUTO_POPULATE_CONTENT = True
DBTEMPLATES_USE_CODEMIRROR = True
# DBTEMPLATES_USE_TINYMCE = True
