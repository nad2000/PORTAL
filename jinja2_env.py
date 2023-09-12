from os.path import basename

from django.templatetags.static import static
from django.urls import reverse
from django.utils import translation
from jinja2 import Environment, PackageLoader


def environment(**options):
    options.update({"extensions": ["jinja2.ext.i18n"]})
    env = Environment(**options)
    env.globals.update(
        {
            "static": static,
            "url": reverse,
        }
    )
    env.filters["basename"] = basename
    env.install_gettext_translations(translation)
    return env
