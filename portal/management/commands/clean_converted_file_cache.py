from django.core.management.base import BaseCommand

from portal import models
from django.conf import settings


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
            default=200,
        )
        parser.add_argument(
            "--site",
            type=int,
            help="Site",
            default=None,
        )
        return parser

    def handle(self, *args, **options):
        models.ConvertedFile.objects = models.ConvertedFile.all_objects

        if site_id := options.get("site"):
            models.clean_converted_file_cache(
                dry_run=options.get("dry_run"), keep_days=options.get("keep", 200), site_id=site_id
            )
        else:
            for s in models.Site.objects.all():
                print(f"SITE: {s}")
                models.clean_converted_file_cache(
                    dry_run=options.get("dry_run"),
                    keep_days=options.get("keep", 200),
                    site_id=s.pk,
                )
