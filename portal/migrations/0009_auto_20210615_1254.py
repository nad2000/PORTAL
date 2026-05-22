import django.core.validators
import django.db.models.deletion
import django_fsm
import private_storage.fields
import private_storage.storage.files
from django.db import migrations, models

import common.models
import portal.models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0008_auto_20210603_1239"),
    ]

    operations = [
        migrations.CreateModel(
            name="EthicsStatement",
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
                    "file",
                    private_storage.fields.PrivateFileField(
                        blank=True,
                        help_text="Please upload human or animal ethics statement.",
                        null=True,
                        storage=private_storage.storage.files.PrivateFileSystemStorage(),
                        upload_to="",
                        verbose_name="ethics statement",
                    ),
                ),
                ("not_relevant", models.BooleanField(default=False)),
                (
                    "comment",
                    models.TextField(
                        blank=True, max_length=1000, null=True, verbose_name="Comment"
                    ),
                ),
            ],
            options={
                "db_table": "ethics_statement",
            },
            bases=(portal.models.PdfFileMixin, common.models.HelperMixin, models.Model),
        ),
        migrations.CreateModel(
            name="Testimonial",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("summary", models.TextField(blank=True, null=True)),
                (
                    "file",
                    private_storage.fields.PrivateFileField(
                        blank=True,
                        help_text="Please upload your endorsement, testimonial, or feedback",
                        null=True,
                        storage=private_storage.storage.files.PrivateFileSystemStorage(),
                        upload_to="",
                        verbose_name="endorsement, testimonial, or feedback",
                    ),
                ),
                ("state", django_fsm.FSMField(default="new", max_length=50)),
                (
                    "converted_file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="portal.convertedfile",
                    ),
                ),
                (
                    "cv",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="portal.curriculumvitae",
                    ),
                ),
                (
                    "referee",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="testimonial",
                        to="portal.referee",
                    ),
                ),
            ],
            options={
                "db_table": "testimonial",
            },
            bases=(portal.models.PdfFileMixin, common.models.HelperMixin, models.Model),
        ),
        migrations.RemoveField(
            model_name="testimony",
            name="converted_file",
        ),
        migrations.RemoveField(
            model_name="testimony",
            name="referee",
        ),
        migrations.DeleteModel(
            name="SchemeApplicationGroup",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="animal_ethics_required",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="cv_required",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="description",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="description_en",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="description_mi",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="groups",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="guidelines",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="pid_required",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="presentation_required",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="research_summary_required",
        ),
        migrations.RemoveField(
            model_name="scheme",
            name="team_can_apply",
        ),
        migrations.AddField(
            model_name="application",
            name="budget",
            field=private_storage.fields.PrivateFileField(
                blank=True,
                help_text="Please upload completed application budget spreadsheet",
                null=True,
                storage=private_storage.storage.files.PrivateFileSystemStorage(),
                upload_to="",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=[
                            "xls",
                            "xlw",
                            "xlt",
                            "xml",
                            "xlsx",
                            "xlsm",
                            "xltx",
                            "xltm",
                            "xlsb",
                            "csv",
                            "ctv",
                        ]
                    )
                ],
                verbose_name="completed application budget spreadsheet",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="portal.curriculumvitae",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="budget",
            field=models.TextField(
                blank=True,
                help_text="Please upload completed application budget spreadsheet",
                max_length=100,
                null=True,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=[
                            "xls",
                            "xlw",
                            "xlt",
                            "xml",
                            "xlsx",
                            "xlsm",
                            "xltx",
                            "xltm",
                            "xlsb",
                            "csv",
                            "ctv",
                        ]
                    )
                ],
                verbose_name="completed application budget spreadsheet",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.curriculumvitae",
            ),
        ),
        migrations.AddField(
            model_name="historicalnomination",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.curriculumvitae",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="applicant_cv_required",
            field=models.BooleanField(
                default=True, verbose_name="Applicant/Team representative CV required"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="budget_template",
            field=models.TextField(
                blank=True,
                max_length=100,
                null=True,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=[
                            "xls",
                            "xlw",
                            "xlt",
                            "xml",
                            "xlsx",
                            "xlsm",
                            "xltx",
                            "xltm",
                            "xlsb",
                            "csv",
                            "ctv",
                        ]
                    )
                ],
                verbose_name="Budget Template",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="can_nominate",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="description",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="description_en",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="description_mi",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="direct_application_allowed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="ethics_statement_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="guidelines",
            field=models.CharField(
                blank=True, max_length=120, null=True, verbose_name="guideline link URL"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="nominator_cv_required",
            field=models.BooleanField(default=True, verbose_name="Nominator CV required"),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="pid_required",
            field=models.BooleanField(default=True, verbose_name="photo ID required"),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="presentation_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="referee_cv_required",
            field=models.BooleanField(default=True, verbose_name="Referee CV required"),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="research_summary_required",
            field=models.BooleanField(default=False, verbose_name="research summary required"),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="team_can_apply",
            field=models.BooleanField(default=False, verbose_name="can be submitted by a team"),
        ),
        migrations.AddField(
            model_name="nomination",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="portal.curriculumvitae",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="applicant_cv_required",
            field=models.BooleanField(
                default=True, verbose_name="Applicant/Team representative CV required"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="budget_template",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=portal.models.round_template_path,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=[
                            "xls",
                            "xlw",
                            "xlt",
                            "xml",
                            "xlsx",
                            "xlsm",
                            "xltx",
                            "xltm",
                            "xlsb",
                            "csv",
                            "ctv",
                        ]
                    )
                ],
                verbose_name="Budget Template",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="can_nominate",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="round",
            name="description",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="description_en",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="description_mi",
            field=models.TextField(
                blank=True, max_length=1000, null=True, verbose_name="short description"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="direct_application_allowed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="round",
            name="ethics_statement_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="round",
            name="guidelines",
            field=models.CharField(
                blank=True, max_length=120, null=True, verbose_name="guideline link URL"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="nominator_cv_required",
            field=models.BooleanField(default=True, verbose_name="Nominator CV required"),
        ),
        migrations.AddField(
            model_name="round",
            name="pid_required",
            field=models.BooleanField(default=True, verbose_name="photo ID required"),
        ),
        migrations.AddField(
            model_name="round",
            name="presentation_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="round",
            name="referee_cv_required",
            field=models.BooleanField(default=True, verbose_name="Referee CV required"),
        ),
        migrations.AddField(
            model_name="round",
            name="research_summary_required",
            field=models.BooleanField(default=False, verbose_name="research summary required"),
        ),
        migrations.AddField(
            model_name="round",
            name="team_can_apply",
            field=models.BooleanField(default=False, verbose_name="can be submitted by a team"),
        ),
        migrations.AlterField(
            model_name="application",
            name="is_tac_accepted",
            field=models.BooleanField(
                default=False, verbose_name="I have read and accept Terms and Conditions"
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="round",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="portal.round",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="is_tac_accepted",
            field=models.BooleanField(
                default=False, verbose_name="I have read and accept Terms and Conditions"
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="is_accepted",
            field=models.BooleanField(default=False, verbose_name="Privacy Policy Accepted"),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="primary_language_spoken",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Afrikaans", "Afrikaans"),
                    ("Arabic", "Arabic"),
                    ("Bahasa Indonesia", "Bahasa Indonesia"),
                    ("Chinese (not further defined)", "Chinese (not further defined)"),
                    ("Cook Islands Māori", "Cook Islands Māori"),
                    ("Dutch", "Dutch"),
                    ("English (New Zealand English)", "English (New Zealand English)"),
                    ("Fijian", "Fijian"),
                    ("French", "French"),
                    ("German", "German"),
                    ("Gujarati", "Gujarati"),
                    ("Hindi", "Hindi"),
                    ("Italian", "Italian"),
                    ("Japanese", "Japanese"),
                    ("Khmer", "Khmer"),
                    ("Korean", "Korean"),
                    ("Malayalam", "Malayalam"),
                    ("Malaysian", "Malaysian"),
                    ("Mandarin Chinese", "Mandarin Chinese"),
                    ("Min Chinese", "Min Chinese"),
                    ("Māori", "Māori"),
                    ("New Zealand Sign Language", "New Zealand Sign Language"),
                    ("Niuean", "Niuean"),
                    ("Other", "Other"),
                    ("Persian", "Persian"),
                    ("Punjabi", "Punjabi"),
                    ("Russian", "Russian"),
                    ("Samoan", "Samoan"),
                    ("Serbo-Croatian", "Serbo-Croatian"),
                    ("Sinhala", "Sinhala"),
                    ("Spanish", "Spanish"),
                    ("Tagalog", "Tagalog"),
                    ("Tamil", "Tamil"),
                    ("Thai", "Thai"),
                    ("Tongan", "Tongan"),
                    ("Urdu", "Urdu"),
                    ("Vietnamese", "Vietnamese"),
                    ("Yue Chinese (Cantonese)", "Yue Chinese (Cantonese)"),
                ],
                max_length=40,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="is_accepted",
            field=models.BooleanField(default=False, verbose_name="Privacy Policy Accepted"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="primary_language_spoken",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Afrikaans", "Afrikaans"),
                    ("Arabic", "Arabic"),
                    ("Bahasa Indonesia", "Bahasa Indonesia"),
                    ("Chinese (not further defined)", "Chinese (not further defined)"),
                    ("Cook Islands Māori", "Cook Islands Māori"),
                    ("Dutch", "Dutch"),
                    ("English (New Zealand English)", "English (New Zealand English)"),
                    ("Fijian", "Fijian"),
                    ("French", "French"),
                    ("German", "German"),
                    ("Gujarati", "Gujarati"),
                    ("Hindi", "Hindi"),
                    ("Italian", "Italian"),
                    ("Japanese", "Japanese"),
                    ("Khmer", "Khmer"),
                    ("Korean", "Korean"),
                    ("Malayalam", "Malayalam"),
                    ("Malaysian", "Malaysian"),
                    ("Mandarin Chinese", "Mandarin Chinese"),
                    ("Min Chinese", "Min Chinese"),
                    ("Māori", "Māori"),
                    ("New Zealand Sign Language", "New Zealand Sign Language"),
                    ("Niuean", "Niuean"),
                    ("Other", "Other"),
                    ("Persian", "Persian"),
                    ("Punjabi", "Punjabi"),
                    ("Russian", "Russian"),
                    ("Samoan", "Samoan"),
                    ("Serbo-Croatian", "Serbo-Croatian"),
                    ("Sinhala", "Sinhala"),
                    ("Spanish", "Spanish"),
                    ("Tagalog", "Tagalog"),
                    ("Tamil", "Tamil"),
                    ("Thai", "Thai"),
                    ("Tongan", "Tongan"),
                    ("Urdu", "Urdu"),
                    ("Vietnamese", "Vietnamese"),
                    ("Yue Chinese (Cantonese)", "Yue Chinese (Cantonese)"),
                ],
                max_length=40,
                null=True,
            ),
        ),
        migrations.DeleteModel(
            name="Testimony",
        ),
        migrations.AddField(
            model_name="ethicsstatement",
            name="application",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ethics_statement",
                to="portal.application",
            ),
        ),
    ]
