from django.core.management.base import BaseCommand

from portal import models


class Command(BaseCommand):
    help = "Invite referees after the round closes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform dry run.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Force referee invitations.",
        )
        return parser

    def handle(self, *args, **options):
        by = models.User.where(username="applications").first()
        models.invite_referees(
            site_id=5, after_round_closes=not options.get("force", False), by=by
        )
