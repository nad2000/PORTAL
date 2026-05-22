from django.core.management.base import BaseCommand

from portal import models
from django.conf import settings
from loguru import logger


class Command(BaseCommand):
    help = "Sent reporting reminders and initiate new reports"

    # def add_arguments(self, parser):
    #     parser.add_argument(
    #         "--dry-run",
    #         action="store_true",
    #         help="Perform dry run.",
    #     )
    #     return parser

    def handle(self, *args, **options):
        for site_id in [4, 5]:
            settings.SITE_ID = site_id
            # models.refresh_page_counts(dry_run=options.get("dry_run"))
            reports = list(models.Contract.start_reporting())
            if reports:
                logger.info(f"Created {len(reports)} report(s).")
                for r in reports:
                    logger.info(f"** {r}")
