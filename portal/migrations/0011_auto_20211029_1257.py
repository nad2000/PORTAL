import common.models
from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import model_utils.fields
import portal.models
import private_storage.fields
import private_storage.storage.files
import simple_history.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0010_auto_20210716_2057"),
    ]

    operations = [
        migrations.AlterField(
            model_name="academicrecord",
            name="awarded_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="portal.organisation",
                verbose_name="awarded by",
            ),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="conferred_on",
            field=models.DateField(blank=True, null=True, verbose_name="conferred on"),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="discipline",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="portal.fieldofstudy",
                verbose_name="discipline",
            ),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="put_code",
            field=models.PositiveIntegerField(
                blank=True, editable=False, null=True, verbose_name="put-code"
            ),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="qualification",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="portal.qualification",
                verbose_name="qualification",
            ),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="research_topic",
            field=models.CharField(
                blank=True, max_length=80, null=True, verbose_name="research topic"
            ),
        ),
        migrations.AlterField(
            model_name="academicrecord",
            name="start_year",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1960),
                    django.core.validators.MaxValueValidator(2099),
                ],
                verbose_name="start year",
            ),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="end_date",
            field=models.DateField(blank=True, null=True, verbose_name="end date"),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="put_code",
            field=models.PositiveIntegerField(
                blank=True, editable=False, null=True, verbose_name="put-code"
            ),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="qualification",
            field=models.CharField(
                blank=True, max_length=512, null=True, verbose_name="qualification"
            ),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="role",
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name="role"),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="start_date",
            field=models.DateField(blank=True, null=True, verbose_name="start date"),
        ),
        migrations.AlterField(
            model_name="affiliation",
            name="type",
            field=models.CharField(
                choices=[
                    ("EDU", "Education"),
                    ("EMP", "Employment"),
                    ("MEM", "Membership"),
                    ("SER", "Service"),
                ],
                max_length=10,
                verbose_name="type",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="application_title",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="city",
            field=models.CharField(max_length=80, verbose_name="city"),
        ),
        migrations.AlterField(
            model_name="application",
            name="converted_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="portal.convertedfile",
                verbose_name="converted file",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="portal.curriculumvitae",
                verbose_name="curriculum vitae",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="email",
            field=common.models.EmailField(
                blank=True, max_length=254, verbose_name="email address"
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="first_name",
            field=models.CharField(max_length=30, verbose_name="first name"),
        ),
        migrations.AlterField(
            model_name="application",
            name="is_bilingual_summary",
            field=models.BooleanField(default=False, verbose_name="is bilingual summary"),
        ),
        migrations.AlterField(
            model_name="application",
            name="is_team_application",
            field=models.BooleanField(default=False, verbose_name="team application"),
        ),
        migrations.AlterField(
            model_name="application",
            name="last_name",
            field=models.CharField(max_length=150, verbose_name="last name"),
        ),
        migrations.AlterField(
            model_name="application",
            name="number",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=24,
                null=True,
                unique=True,
                verbose_name="number",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="organisation",
            field=models.CharField(max_length=200, verbose_name="organisation"),
        ),
        migrations.AlterField(
            model_name="application",
            name="position",
            field=models.CharField(max_length=80, verbose_name="position"),
        ),
        migrations.AlterField(
            model_name="application",
            name="postal_address",
            field=models.CharField(max_length=120, verbose_name="postal address"),
        ),
        migrations.AlterField(
            model_name="application",
            name="postcode",
            field=models.CharField(max_length=4, verbose_name="postcode"),
        ),
        migrations.AlterField(
            model_name="application",
            name="round",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="portal.round",
                verbose_name="round",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="state",
            field=portal.models.StatusField(
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                verbose_name="state",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to=settings.AUTH_USER_MODEL,
                verbose_name="submitted by",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="summary",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="application",
            name="summary_en",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="application",
            name="summary_mi",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="application",
            name="tac_accepted_at",
            field=model_utils.fields.MonitorField(
                monitor="state",
                verbose_name="Terms and Conditions accepted at",
                when={"tac_accepted"},
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="team_name",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="team name"
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="title",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MR", "Mr"),
                    ("MRS", "Mrs"),
                    ("MS", "Ms"),
                    ("DR", "Dr"),
                    ("PROF", "Prof"),
                ],
                max_length=40,
                null=True,
                verbose_name="title",
            ),
        ),
        migrations.AlterField(
            model_name="curriculumvitae",
            name="converted_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="portal.convertedfile",
                verbose_name="converted file",
            ),
        ),
        migrations.AlterField(
            model_name="curriculumvitae",
            name="file",
            field=private_storage.fields.PrivateFileField(
                storage=private_storage.storage.files.PrivateFileSystemStorage(),
                upload_to="",
                verbose_name="file",
            ),
        ),
        migrations.AlterField(
            model_name="curriculumvitae",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
                verbose_name="owner",
            ),
        ),
        migrations.AlterField(
            model_name="curriculumvitae",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="portal.profile",
                verbose_name="profile",
            ),
        ),
        migrations.AlterField(
            model_name="ethicsstatement",
            name="not_relevant",
            field=models.BooleanField(default=False, verbose_name="Not Applicable"),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="comment",
            field=models.TextField(default="", verbose_name="Overall Comment"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="end_date",
            field=models.DateField(blank=True, null=True, verbose_name="end date"),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="put_code",
            field=models.PositiveIntegerField(
                blank=True, editable=False, null=True, verbose_name="put-code"
            ),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="qualification",
            field=models.CharField(
                blank=True, max_length=512, null=True, verbose_name="qualification"
            ),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="role",
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name="role"),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="start_date",
            field=models.DateField(blank=True, null=True, verbose_name="start date"),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="type",
            field=models.CharField(
                choices=[
                    ("EDU", "Education"),
                    ("EMP", "Employment"),
                    ("MEM", "Membership"),
                    ("SER", "Service"),
                ],
                max_length=10,
                verbose_name="type",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="application_title",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="city",
            field=models.CharField(max_length=80, verbose_name="city"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="converted_file",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.convertedfile",
                verbose_name="converted file",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.curriculumvitae",
                verbose_name="curriculum vitae",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="email",
            field=common.models.EmailField(
                blank=True, max_length=254, verbose_name="email address"
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="first_name",
            field=models.CharField(max_length=30, verbose_name="first name"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="is_bilingual_summary",
            field=models.BooleanField(default=False, verbose_name="is bilingual summary"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="is_team_application",
            field=models.BooleanField(default=False, verbose_name="team application"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="last_name",
            field=models.CharField(max_length=150, verbose_name="last name"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="number",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=24,
                null=True,
                verbose_name="number",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="organisation",
            field=models.CharField(max_length=200, verbose_name="organisation"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="position",
            field=models.CharField(max_length=80, verbose_name="position"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="postal_address",
            field=models.CharField(max_length=120, verbose_name="postal address"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="postcode",
            field=models.CharField(max_length=4, verbose_name="postcode"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="round",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.round",
                verbose_name="round",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="state",
            field=portal.models.StatusField(
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                verbose_name="state",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="submitted by",
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="summary",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="summary_en",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="summary_mi",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="tac_accepted_at",
            field=model_utils.fields.MonitorField(
                monitor="state",
                verbose_name="Terms and Conditions accepted at",
                when={"tac_accepted"},
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="team_name",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="team name"
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="title",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MR", "Mr"),
                    ("MRS", "Mrs"),
                    ("MS", "Ms"),
                    ("DR", "Dr"),
                    ("PROF", "Prof"),
                ],
                max_length=40,
                null=True,
                verbose_name="title",
            ),
        ),
        migrations.AlterField(
            model_name="historicalevaluation",
            name="comment",
            field=models.TextField(default="", verbose_name="Overall Comment"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="historicalmember",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="historicalmember",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="application",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.application",
                verbose_name="application",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.curriculumvitae",
                verbose_name="Curriculum Vitae",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="email",
            field=common.models.EmailField(
                help_text="Email address of the nominee",
                max_length=254,
                verbose_name="email address",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="first_name",
            field=models.CharField(max_length=30, verbose_name="first name"),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="last_name",
            field=models.CharField(max_length=150, verbose_name="last name"),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="round",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.round",
                verbose_name="round",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
                verbose_name="status",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="title",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MR", "Mr"),
                    ("MRS", "Mrs"),
                    ("MS", "Ms"),
                    ("DR", "Dr"),
                    ("PROF", "Prof"),
                ],
                max_length=40,
                null=True,
                verbose_name="title",
            ),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="user",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="user",
            ),
        ),
        migrations.AlterField(
            model_name="historicalpanellist",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="historicalpanellist",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="date_of_birth",
            field=models.DateField(
                blank=True,
                null=True,
                validators=[portal.models.validate_bod],
                verbose_name="date of birth",
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="education_level",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (0, "No Qualification"),
                    (1, "Level 1 Certificate"),
                    (2, "Level 2 Certificate"),
                    (3, "Level 3 Certificate"),
                    (4, "Level 4 Certificate"),
                    (5, "Level 5 Diploma/Certificate"),
                    (6, "Level 6 Graduate Certificate, Level 6 Diploma/Certificate"),
                    (
                        7,
                        "Bachelor Degree, Level 7 Graduate Diploma/Certificate, Level 7 Diploma/ Certificate",
                    ),
                    (8, "Postgraduate Diploma/Certificate, Bachelor Honours"),
                    (9, "Masters Degree"),
                    (10, "Doctorate Degree"),
                    (23, "Overseas Secondary School Qualification"),
                    (94, "Don't Know"),
                ],
                null=True,
                verbose_name="education level",
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="employment_status",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (1, "Paid employee"),
                    (2, "Employer"),
                    (3, "Self-employed and without employees"),
                    (4, "Unpaid family worker"),
                    (6, "Student"),
                    (5, "Not stated"),
                ],
                null=True,
                verbose_name="employment status",
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="gender",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Prefer not to say"),
                    (1, "Male"),
                    (2, "Female"),
                    (3, "Gender diverse"),
                ],
                default=0,
                null=True,
                verbose_name="gender",
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="is_accepted",
            field=models.BooleanField(default=False, verbose_name="privacy policy accepted"),
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
                verbose_name="primary language spoken",
            ),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="user",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="user",
            ),
        ),
        migrations.AlterField(
            model_name="historicalreferee",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="historicalreferee",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="closes_on",
            field=models.DateField(blank=True, null=True, verbose_name="closes on"),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="opens_on",
            field=models.DateField(blank=True, null=True, verbose_name="opens on"),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="scheme",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="portal.scheme",
                verbose_name="scheme",
            ),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="title",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="title_en",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="title_mi",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="identityverification",
            name="application",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="identity_verification",
                to="portal.application",
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="email",
            field=common.models.EmailField(max_length=254, verbose_name="email address"),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="first_name",
            field=models.CharField(max_length=30, verbose_name="first name"),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="last_name",
            field=models.CharField(max_length=150, verbose_name="last name"),
        ),
        migrations.AlterField(
            model_name="maillog",
            name="subject",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="member",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="member",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="application",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="nomination",
                to="portal.application",
                verbose_name="application",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="portal.curriculumvitae",
                verbose_name="Curriculum Vitae",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="email",
            field=common.models.EmailField(
                help_text="Email address of the nominee",
                max_length=254,
                verbose_name="email address",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="first_name",
            field=models.CharField(max_length=30, verbose_name="first name"),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="last_name",
            field=models.CharField(max_length=150, verbose_name="last name"),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="round",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="nominations",
                to="portal.round",
                verbose_name="round",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
                verbose_name="status",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="title",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MR", "Mr"),
                    ("MRS", "Mrs"),
                    ("MS", "Ms"),
                    ("DR", "Dr"),
                    ("PROF", "Prof"),
                ],
                max_length=40,
                null=True,
                verbose_name="title",
            ),
        ),
        migrations.AlterField(
            model_name="nomination",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="nominations_to_apply",
                to=settings.AUTH_USER_MODEL,
                verbose_name="user",
            ),
        ),
        migrations.AlterField(
            model_name="nominee",
            name="email",
            field=common.models.EmailField(max_length=254, verbose_name="email address"),
        ),
        migrations.AlterField(
            model_name="panellist",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="panellist",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="career_stages",
            field=models.ManyToManyField(
                blank=True,
                through="portal.ProfileCareerStage",
                to="portal.CareerStage",
                verbose_name="career stages",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="date_of_birth",
            field=models.DateField(
                blank=True,
                null=True,
                validators=[portal.models.validate_bod],
                verbose_name="date of birth",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="education_level",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (0, "No Qualification"),
                    (1, "Level 1 Certificate"),
                    (2, "Level 2 Certificate"),
                    (3, "Level 3 Certificate"),
                    (4, "Level 4 Certificate"),
                    (5, "Level 5 Diploma/Certificate"),
                    (6, "Level 6 Graduate Certificate, Level 6 Diploma/Certificate"),
                    (
                        7,
                        "Bachelor Degree, Level 7 Graduate Diploma/Certificate, Level 7 Diploma/ Certificate",
                    ),
                    (8, "Postgraduate Diploma/Certificate, Bachelor Honours"),
                    (9, "Masters Degree"),
                    (10, "Doctorate Degree"),
                    (23, "Overseas Secondary School Qualification"),
                    (94, "Don't Know"),
                ],
                null=True,
                verbose_name="education level",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="employment_status",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (1, "Paid employee"),
                    (2, "Employer"),
                    (3, "Self-employed and without employees"),
                    (4, "Unpaid family worker"),
                    (6, "Student"),
                    (5, "Not stated"),
                ],
                null=True,
                verbose_name="employment status",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="ethnicities",
            field=models.ManyToManyField(
                blank=True,
                db_table="profile_ethnicity",
                to="portal.Ethnicity",
                verbose_name="ethnicities",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="external_ids",
            field=models.ManyToManyField(
                blank=True,
                through="portal.ProfilePersonIdentifier",
                to="portal.PersonIdentifierType",
                verbose_name="external IDs",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="gender",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Prefer not to say"),
                    (1, "Male"),
                    (2, "Female"),
                    (3, "Gender diverse"),
                ],
                default=0,
                null=True,
                verbose_name="gender",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="is_accepted",
            field=models.BooleanField(default=False, verbose_name="privacy policy accepted"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="iwi_groups",
            field=models.ManyToManyField(
                blank=True,
                db_table="profile_iwi_group",
                to="portal.IwiGroup",
                verbose_name="iwi groups",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="languages_spoken",
            field=models.ManyToManyField(
                blank=True,
                db_table="profile_language",
                to="portal.Language",
                verbose_name="languages spoken",
            ),
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
                verbose_name="primary language spoken",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="user",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
                verbose_name="user",
            ),
        ),
        migrations.AlterField(
            model_name="profilecareerstage",
            name="career_stage",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="portal.careerstage",
                verbose_name="career stage",
            ),
        ),
        migrations.AlterField(
            model_name="profilecareerstage",
            name="year_achieved",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Year that you first attained the career stage",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1900),
                    django.core.validators.MaxValueValidator(2100),
                ],
                verbose_name="year achieved",
            ),
        ),
        migrations.AlterField(
            model_name="profilepersonidentifier",
            name="put_code",
            field=models.PositiveIntegerField(
                blank=True, editable=False, null=True, verbose_name="put-code"
            ),
        ),
        migrations.AlterField(
            model_name="profilepersonidentifier",
            name="value",
            field=models.CharField(max_length=100, verbose_name="value"),
        ),
        migrations.AlterField(
            model_name="profileprotectionpattern",
            name="expires_on",
            field=models.DateField(blank=True, null=True, verbose_name="expires on"),
        ),
        migrations.AlterField(
            model_name="profileprotectionpattern",
            name="protection_pattern",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="profile_protection_patterns",
                to="portal.protectionpattern",
                verbose_name="protection pattern",
            ),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="code",
            field=models.PositiveSmallIntegerField(
                primary_key=True, serialize=False, verbose_name="code"
            ),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="comment",
            field=models.TextField(blank=True, max_length=200, null=True, verbose_name="comment"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="comment_en",
            field=models.TextField(blank=True, max_length=200, null=True, verbose_name="comment"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="comment_mi",
            field=models.TextField(blank=True, max_length=200, null=True, verbose_name="comment"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="description",
            field=models.CharField(max_length=80, verbose_name="description"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="description_en",
            field=models.CharField(max_length=80, null=True, verbose_name="description"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="description_mi",
            field=models.CharField(max_length=80, null=True, verbose_name="description"),
        ),
        migrations.AlterField(
            model_name="protectionpattern",
            name="pattern",
            field=models.CharField(max_length=80, verbose_name="pattern"),
        ),
        migrations.AlterField(
            model_name="referee",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="referee",
            name="status",
            field=portal.models.StatusField(
                blank=True,
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="round",
            name="closes_on",
            field=models.DateField(blank=True, null=True, verbose_name="closes on"),
        ),
        migrations.AlterField(
            model_name="round",
            name="opens_on",
            field=models.DateField(blank=True, null=True, verbose_name="opens on"),
        ),
        migrations.AlterField(
            model_name="round",
            name="scheme",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rounds",
                to="portal.scheme",
                verbose_name="scheme",
            ),
        ),
        migrations.AlterField(
            model_name="round",
            name="title",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="round",
            name="title_en",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="round",
            name="title_mi",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="scheme",
            name="code",
            field=models.CharField(blank=True, default="", max_length=10, verbose_name="code"),
        ),
        migrations.AlterField(
            model_name="scheme",
            name="title",
            field=models.CharField(max_length=100, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="scheme",
            name="title_en",
            field=models.CharField(max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="scheme",
            name="title_mi",
            field=models.CharField(max_length=100, null=True, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="email",
            field=common.models.EmailField(max_length=120),
        ),
        migrations.AlterField(
            model_name="testimonial",
            name="converted_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="portal.convertedfile",
                verbose_name="converted file",
            ),
        ),
        migrations.AlterField(
            model_name="testimonial",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="portal.curriculumvitae",
                verbose_name="curriculum vitae",
            ),
        ),
        migrations.AlterField(
            model_name="testimonial",
            name="referee",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="testimonial",
                to="portal.referee",
                verbose_name="referee",
            ),
        ),
        migrations.AlterField(
            model_name="testimonial",
            name="state",
            field=portal.models.StatusField(
                choices=[(0, "dummy")],
                default="new",
                max_length=100,
                no_check_for_status=True,
                verbose_name="state",
            ),
        ),
        migrations.AlterField(
            model_name="testimonial",
            name="summary",
            field=models.TextField(blank=True, null=True, verbose_name="summary"),
        ),
        migrations.CreateModel(
            name="HistoricalInvitation",
            fields=[
                (
                    "id",
                    models.IntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("updated_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "token",
                    models.CharField(
                        db_index=True,
                        default=portal.models.get_unique_invitation_token,
                        max_length=42,
                    ),
                ),
                ("url", models.CharField(blank=True, max_length=200, null=True)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("A", "apply"),
                            ("J", "join"),
                            ("R", "testify"),
                            ("T", "authorize"),
                            ("P", "panellist"),
                        ],
                        default="J",
                        max_length=1,
                    ),
                ),
                ("email", common.models.EmailField(max_length=254, verbose_name="email address")),
                ("first_name", models.CharField(max_length=30, verbose_name="first name")),
                (
                    "middle_names",
                    models.CharField(
                        blank=True,
                        help_text="Comma separated list of middle names",
                        max_length=280,
                        null=True,
                        verbose_name="middle names",
                    ),
                ),
                ("last_name", models.CharField(max_length=150, verbose_name="last name")),
                (
                    "organisation",
                    models.CharField(
                        blank=True, max_length=200, null=True, verbose_name="organisation"
                    ),
                ),
                (
                    "status",
                    portal.models.StatusField(
                        choices=[
                            ("draft", "draft"),
                            ("submitted", "submitted"),
                            ("sent", "sent"),
                            ("accepted", "accepted"),
                            ("expired", "expired"),
                            ("bounced", "bounced"),
                        ],
                        default="draft",
                        max_length=100,
                        no_check_for_status=True,
                    ),
                ),
                (
                    "submitted_at",
                    model_utils.fields.MonitorField(monitor="status", when={"submitted"}),
                ),
                (
                    "sent_at",
                    model_utils.fields.MonitorField(monitor="status", when={"sent"}),
                ),
                (
                    "accepted_at",
                    model_utils.fields.MonitorField(monitor="status", when={"accepted"}),
                ),
                (
                    "expired_at",
                    model_utils.fields.MonitorField(monitor="status", when={"expired"}),
                ),
                (
                    "bounced_at",
                    model_utils.fields.MonitorField(monitor="status", when={"bounced"}),
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
                    "application",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.application",
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
                    "inviter",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.member",
                    ),
                ),
                (
                    "nomination",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.nomination",
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.organisation",
                        verbose_name="organisation",
                    ),
                ),
                (
                    "panellist",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.panellist",
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
                    ),
                ),
                (
                    "round",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="portal.round",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical invitation",
                "db_table": "invitation_history",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": "history_date",
            },
            bases=(
                simple_history.models.HistoricalChanges,
                portal.models.InvitationMixin,
                common.models.HelperMixin,
                models.Model,
            ),
        ),
    ]
