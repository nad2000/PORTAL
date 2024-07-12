from django_extensions.management.jobs import BaseJob

from portal import models


class Job(BaseJob):
    help = "Removes orphaned private files"

    def execute(self):
        models.clean_private_fils()
