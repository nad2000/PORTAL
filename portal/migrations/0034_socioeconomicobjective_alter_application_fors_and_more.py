import common.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0033_applicationfor_application_fors"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocioEconomicObjective",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("code", models.CharField(max_length=6, primary_key=True, serialize=False)),
                ("description", models.CharField(blank=True, max_length=150, null=True)),
                ("source", models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                "verbose_name": "SEO",
                "verbose_name_plural": "SEOs",
                "db_table": "socio_economic_objective",
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.AlterField(
            model_name="application",
            name="fors",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationFor",
                to="portal.fieldofresearch",
                verbose_name="FoRs",
            ),
        ),
        migrations.AlterField(
            model_name="applicationfor",
            name="application",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="application_fors",
                to="portal.application",
            ),
        ),
        migrations.CreateModel(
            name="HistoricalSocioEconomicObjective",
            fields=[
                ("created_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("updated_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("code", models.CharField(db_index=True, max_length=6)),
                ("description", models.CharField(blank=True, max_length=150, null=True)),
                ("source", models.CharField(blank=True, max_length=255, null=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical SEO",
                "verbose_name_plural": "historical SEOs",
                "db_table": "seo_history",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="ApplicationSeo",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("share", models.PositiveSmallIntegerField(blank=True, default=None, null=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_seos",
                        to="portal.application",
                    ),
                ),
                (
                    "code",
                    models.ForeignKey(
                        db_column="code",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="portal.socioeconomicobjective",
                        verbose_name="SEO",
                    ),
                ),
            ],
            options={
                "verbose_name": "application SEO",
                "verbose_name_plural": "application SEOs",
                "db_table": "application_seo",
                "unique_together": {("application", "code")},
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.AddField(
            model_name="application",
            name="seos",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationSeo",
                to="portal.socioeconomicobjective",
                verbose_name="SEOs",
            ),
        ),
    ]
