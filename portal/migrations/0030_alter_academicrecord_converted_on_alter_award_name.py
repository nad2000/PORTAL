from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0029_remove_academicrecord_conferred_on_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="academicrecord",
            name="converted_on",
            field=models.DateField(blank=True, null=True, verbose_name="converted on"),
        ),
        migrations.AlterField(
            model_name="award",
            name="name",
            field=models.CharField(max_length=200, verbose_name="prestigious prize or medal"),
        ),
    ]
