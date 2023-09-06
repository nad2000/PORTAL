from django.core.management.base import BaseCommand

from portal import models


class Command(BaseCommand):
    help = "Removes orphaned private files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        return parser

    def handle(self, *args, **options):
        models.clean_private_fils(dry_run=options.get("dry_run"))
