import common.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0032_alter_historicalaffiliation_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationFor",
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
                        on_delete=django.db.models.deletion.CASCADE, to="portal.application"
                    ),
                ),
                (
                    "code",
                    models.ForeignKey(
                        db_column="code",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="portal.fieldofresearch",
                        verbose_name="FoR",
                    ),
                ),
            ],
            options={
                "verbose_name": "application FOR",
                "verbose_name_plural": "application FORs",
                "db_table": "application_for",
                "unique_together": {("application", "code")},
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.AddField(
            model_name="application",
            name="fors",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationFor",
                to="portal.fieldofresearch",
                verbose_name="FORs",
            ),
        ),
    ]
