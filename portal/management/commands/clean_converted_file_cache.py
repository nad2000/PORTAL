from django.core.management.base import BaseCommand

from portal import models


class Command(BaseCommand):
    help = "Removes converted files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            help="Keep days of data",
            default=90,
        )
        return parser

    def handle(self, *args, **options):
        models.clean_converted_file_cache(dry_run=options.get("dry_run"), keep_days=options.get("keep", 90))
