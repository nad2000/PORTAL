from django_extensions.management.jobs import BaseJob

from portal import models


class Job(BaseJob):
    help = "Invite referees after the round closes"

    def execute(self):
        models.invite_referees_after_round_closes(site_id=5)
