from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0030_alter_academicrecord_converted_on_alter_award_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalinvitation",
            name="first_name",
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name="first name"
            ),
        ),
        migrations.AlterField(
            model_name="historicalinvitation",
            name="last_name",
            field=models.CharField(
                blank=True, max_length=150, null=True, verbose_name="last name"
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="first_name",
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name="first name"
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="last_name",
            field=models.CharField(
                blank=True, max_length=150, null=True, verbose_name="last name"
            ),
        ),
    ]
