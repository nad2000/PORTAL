import django.db.models.deletion
from django.db import migrations, models

import common.models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        ("users", "0003_user_staff_of_sites"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicaluser",
            name="registered_on",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.HelperMixin.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="registered_on",
            field=models.ForeignKey(
                blank=True,
                default=common.models.HelperMixin.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="registered_users",
                to="sites.site",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="staff_of_sites",
            field=models.ManyToManyField(
                blank=True, null=True, related_name="staff_users", to="sites.Site"
            ),
        ),
    ]
