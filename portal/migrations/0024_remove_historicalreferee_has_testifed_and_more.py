import django.db.models.deletion
from django.db import migrations, models

import portal.models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0023_alter_invitation_status_applicationnumber"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="historicalreferee",
            name="has_testifed",
        ),
        migrations.RemoveField(
            model_name="referee",
            name="has_testifed",
        ),
        migrations.AlterField(
            model_name="criterion",
            name="comment",
            field=models.BooleanField(
                default=True, help_text="The panellist should comment their score"
            ),
        ),
        migrations.AlterField(
            model_name="historicalcriterion",
            name="comment",
            field=models.BooleanField(
                default=True, help_text="The panellist should comment their score"
            ),
        ),
        migrations.AlterField(
            model_name="historicalinvitation",
            name="status",
            field=portal.models.StatusField(
                choices=[
                    ("accepted", "accepted"),
                    ("bounced", "bounced"),
                    ("draft", "draft"),
                    ("expired", "expired"),
                    ("revoked", "revoked"),
                    ("sent", "sent"),
                    ("submitted", "submitted"),
                ],
                default="draft",
                max_length=100,
                no_check_for_status=True,
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="application",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitations",
                to="portal.application",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="member",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitation",
                to="portal.member",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="nomination",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitations",
                to="portal.nomination",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="panellist",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitation",
                to="portal.panellist",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="referee",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitation",
                to="portal.referee",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="round",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invitations",
                to="portal.round",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="status",
            field=portal.models.StatusField(
                choices=[
                    ("accepted", "accepted"),
                    ("bounced", "bounced"),
                    ("draft", "draft"),
                    ("expired", "expired"),
                    ("revoked", "revoked"),
                    ("sent", "sent"),
                    ("submitted", "submitted"),
                ],
                default="draft",
                max_length=100,
                no_check_for_status=True,
            ),
        ),
    ]
