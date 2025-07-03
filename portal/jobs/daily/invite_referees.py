from django_extensions.management.jobs import BaseJob

from portal import models


class Job(BaseJob):
    help = "Invite referees after the round closes"

    def execute(self):
        models.invite_referees(site_id=5, after_round_closes=True)
