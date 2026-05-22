import django.db.models.deletion
from django.db import migrations, models

import common.models
import portal.models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0022_historicalround_notify_nominator_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invitation",
            name="status",
            field=portal.models.StatusField(
                choices=[
                    ("draft", "draft"),
                    ("submitted", "submitted"),
                    ("sent", "sent"),
                    ("accepted", "accepted"),
                    ("expired", "expired"),
                    ("bounced", "bounced"),
                    ("revoked", "revoked"),
                ],
                default="draft",
                max_length=100,
                no_check_for_status=True,
            ),
        ),
        migrations.CreateModel(
            name="ApplicationNumber",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "number",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=24,
                        null=True,
                        unique=True,
                        verbose_name="number",
                    ),
                ),
                ("is_active", models.BooleanField(default=False)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="numbers",
                        to="portal.application",
                    ),
                ),
            ],
            options={
                "db_table": "application_number",
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
    ]
