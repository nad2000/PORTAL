from django_extensions.management import jobs

from portal import models
from django.conf import settings
from loguru import logger


class Job(jobs.DailyJob):
    help = "Sent reporting reminders and initiate new reports"

    def execute(self):

        for site_id in [4, 5]:
            settings.SITE_ID.set(site_id)
            # models.refresh_page_counts(dry_run=options.get("dry_run"))
            ## reports = list(models.Contract.start_reporting())
            ## logger.info(f"Report(s) generated: {', '.join(r.number for r in reports)}")
            for r in models.Contract.start_reporting():
                logger.info(f"Report: {r.number} generated")
                # logger.info(f"Report(s) generated: {', '.join(r.number for r in reports)}")
