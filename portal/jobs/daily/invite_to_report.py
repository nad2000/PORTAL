from django_extensions.management.jobs import BaseJob

from portal import models
from django.conf import settings


class Job(BaseJob):
    help = "Sent reporting reminders and initiate new reports"

    def execute(self):

        for site_id in [4, 5]:
            settings.SITE_ID.set(site_id)
            # models.refresh_page_counts(dry_run=options.get("dry_run"))
            reports = list(models.Contract.start_reporting())
