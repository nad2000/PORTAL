from django.conf import settings
from django.core.management.base import BaseCommand
from sentry_sdk import capture_exception

from portal import models


class Command(BaseCommand):
    help = "Sync with the LimeSurvey surveys"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        return parser

    def handle(self, *args, **options):
        by = (
            models.User.where(username="admin").last()
            or models.User.where(username="application").last()
        )
        count = 0
        for site_id in [2, 4, 5]:
            settings.SITE_ID = site_id
            q = models.Round.where(survey_id__isnull=False, scheme__current_round__id=models.F("pk"))
            for r in q:
                try:
                    sync_count = r.sync_referee_surveys(by=by)
                    if sync_count:
                        print(f"{sync_count} referee(s) synced for round {r}")
                        count += sync_count
                except Exception as ex:
                    capture_exception(ex)
                    print(f"{ex}")
            if not count:
                print("All referees were already synced.")
            if q.count() > 1:
                print(f"In total synced {count} referee(s)")
