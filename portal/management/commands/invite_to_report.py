from django.core.management.base import BaseCommand

from portal import models


class Command(BaseCommand):
    help = "Sent reporting reminders"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        return parser

    def handle(self, *args, **options):
        models.refresh_page_counts(dry_run=options.get("dry_run"))
