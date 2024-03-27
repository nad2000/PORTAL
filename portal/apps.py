from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PortalConfig(AppConfig):
    name = "portal"
    verbose_name = _("RSTA Portal")

    def ready(self):
        try:
            from . import signals  # noqa F401
        except ImportError:
            pass
