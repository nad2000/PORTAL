from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicaluser",
            name="is_approved",
            field=models.BooleanField(default=False, verbose_name="Is Approved"),
        ),
        migrations.AlterField(
            model_name="user",
            name="is_approved",
            field=models.BooleanField(default=False, verbose_name="Is Approved"),
        ),
    ]
