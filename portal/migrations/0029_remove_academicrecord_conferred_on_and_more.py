import private_storage.fields
import private_storage.storage.files
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0028_historicaltestimonial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="academicrecord",
            old_name="conferred_on",
            new_name="converted_on",
        ),
        migrations.AlterField(
            model_name="convertedfile",
            name="file",
            field=private_storage.fields.PrivateFileField(
                storage=private_storage.storage.files.PrivateFileSystemStorage(),
                upload_to="converted/%Y/%m/%d",
            ),
        ),
    ]
