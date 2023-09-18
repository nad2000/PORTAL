import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models

import common.models
import portal.models


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0027_historicalpanellist_status_changed_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalTestimonial",
            fields=[
                (
                    "id",
                    models.IntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("updated_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("summary", models.TextField(blank=True, null=True, verbose_name="summary")),
                (
                    "file",
                    models.TextField(
                        blank=True,
                        help_text="Please upload your endorsement, testimonial, or feedback",
                        max_length=100,
                        null=True,
                        verbose_name="endorsement, testimonial, or feedback",
                    ),
                ),
                (
                    "state",
                    portal.models.StatusField(
                        choices=[
                            (None, None),
                            ("new", "new"),
                            ("draft", "draft"),
                            ("submitted", "submitted"),
                        ],
                        default="new",
                        max_length=100,
                        no_check_for_status=True,
                        verbose_name="state",
                    ),
                ),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField()),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "converted_file",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.convertedfile",
                        verbose_name="converted file",
                    ),
                ),
                (
                    "cv",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.curriculumvitae",
                        verbose_name="curriculum vitae",
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
                (
                    "referee",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.referee",
                        verbose_name="referee",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        default=common.models.Model.get_current_site_id,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="sites.site",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical testimonial",
                "db_table": "testimonial_history",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": "history_date",
            },
            bases=(
                simple_history.models.HistoricalChanges,
                portal.models.TestimonialMixin,
                common.models.HelperMixin,
                models.Model,
            ),
        ),
    ]
