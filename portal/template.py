from django.template.loaders.cached import Loader
from django.template.loaders.filesystem import Loader as FilesystemLoader
from django.conf import settings
import os
from django.contrib.sites.models import Site
from django import VERSION as django_version


class Loader(Loader):
    def cache_key(self, template_name, skip=None):
        return f"{settings.SITE_ID}-{super().cache_key(template_name, skip=skip)}"


class MultisiteLoader(FilesystemLoader):
    def get_template_sources(self, template_name, *args, **kwargs):
        # domain = Site.objects.get_current().domain
        site_id = settings.SITE_ID
        default_dir = getattr(settings, "MULTISITE_DEFAULT_TEMPLATE_DIR", "default")
        for tname in (
            os.path.join(f"sites/{site_id}", template_name),
            os.path.join(default_dir, template_name),
        ):
            for item in super(MultisiteLoader, self).get_template_sources(tname, **kwargs):
                yield item


# vim:set ft=python.django:
