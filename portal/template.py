from django.template.loaders.cached import Loader
from django.conf import settings


class Loader(Loader):

    def cache_key(self, template_name, skip=None):
        return f"{settings.SITE_ID}-{super().cache_key(template_name, skip=skip)}"


# vim:set ft=python.django:
