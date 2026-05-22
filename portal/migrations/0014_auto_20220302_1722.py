import django.contrib.sites.managers
import django.db.models.deletion
from django.db import migrations, models

import common.models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        ("portal", "0013_auto_20220228_1641"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="convertedfile",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="maillog",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="subscription",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AddField(
            model_name="convertedfile",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="maillog",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.DeleteModel(
            name="Nominee",
        ),
    ]
