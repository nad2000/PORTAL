import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0020_historicalprofile_account_approval_message_sent_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalround",
            name="tac",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="tac_en",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="tac_mi",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="tac",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="tac_en",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="tac_mi",
            field=models.TextField(
                blank=True,
                help_text="Terms and Conditions",
                max_length=10000,
                null=True,
                verbose_name="T&C",
            ),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="role",
            field=models.CharField(
                blank=True,
                help_text="position or role, e.g., student, postdoc, etc.",
                max_length=512,
                null=True,
                verbose_name="role",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="position",
            field=models.CharField(
                help_text="position or role, e.g., student, postdoc, etc.",
                max_length=80,
                verbose_name="position",
            ),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="role",
            field=models.CharField(
                blank=True,
                help_text="position or role, e.g., student, postdoc, etc.",
                max_length=512,
                null=True,
                verbose_name="role",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="position",
            field=models.CharField(
                help_text="position or role, e.g., student, postdoc, etc.",
                max_length=80,
                verbose_name="position",
            ),
        ),
        migrations.AlterField(
            model_name="profilepersonidentifier",
            name="code",
            field=models.ForeignKey(
                help_text="Choose a type or enter a new identifier or reference type",
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="portal.personidentifiertype",
                verbose_name="type",
            ),
        ),
        migrations.AlterField(
            model_name="profilepersonidentifier",
            name="value",
            field=models.CharField(max_length=100, verbose_name="Identifier or reference"),
        ),
    ]
