import django.contrib.sites.managers
import django.db.models.deletion
from django.db import migrations, models

import common.models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        ("portal", "0012_auto_20211030_1531"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="application",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="invitation",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="nomination",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="panellist",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="round",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="scheme",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="testimonial",
            managers=[
                ("objects", django.contrib.sites.managers.CurrentSiteManager()),
            ],
        ),
        migrations.AddField(
            model_name="application",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="site",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.Model.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="historicalinvitation",
            name="site",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.Model.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="historicalnomination",
            name="site",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.Model.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="historicalpanellist",
            name="site",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.Model.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="site",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                default=common.models.Model.get_current_site_id,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="invitation",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="nomination",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="panellist",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="scheme",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
        migrations.AddField(
            model_name="testimonial",
            name="site",
            field=models.ForeignKey(
                default=common.models.Model.get_current_site_id,
                on_delete=django.db.models.deletion.PROTECT,
                to="sites.site",
            ),
        ),
    ]
