from django_extensions.management import jobs

from portal import models
from django.conf import settings
from loguru import logger


class Job(jobs.HourlyJob):
    help = "test"

    def execute(self):

        for site_id in [4, 5]:
            settings.SITE_ID.set(site_id)
            # models.refresh_page_counts(dry_run=options.get("dry_run"))
            # reports = list(models.Contract.start_reporting())
            logger.info("TEST!")
            logger.warning("WARNING!")
            logger.error("ERROR!")
