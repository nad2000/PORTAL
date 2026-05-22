from django_extensions.management.jobs import BaseJob

from portal import models


class Job(BaseJob):
    help = "Notify site staff about new organisations"

    def execute(self):
        models.notify_site_staff_about_new_organisations()
