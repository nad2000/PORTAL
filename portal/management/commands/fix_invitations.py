from django.core.management.base import BaseCommand

from portal import models


class Command(BaseCommand):
    help = "Fix invitations and assigne the round to the records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        return parser

    def handle(self, *args, **options):
        c = models.Invitation.update_round(dry_run=options.get("dry_run"))
        print(f"Updated {c} invitation records")
