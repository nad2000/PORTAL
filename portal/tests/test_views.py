from io import BytesIO

import pytest
from django.conf import settings
# from background_task.tasks import tasks
from django.contrib.auth import get_user_model
from django.contrib.flatpages.models import FlatPage

from portal import models
from portal.models import Ethnicity, Person, Subscription

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_template_views(client, admin_user):
    resp = client.get("/")
    assert resp.status_code == 302

    fp, _ = FlatPage.objects.get_or_create(
        title="About (en)", url="/en/about/", content="THIS IS EN ABOUT PAGE"
    )
    fp.sites.add(settings.SITE_ID)
    fp.save()

    resp = client.get("/pages/en/about/")
    assert resp.status_code == 200

    resp = client.get("/pages/about/")
    assert resp.status_code == 200

    resp = client.get("/about")
    assert resp.status_code == 200

    resp = client.get("/accounts/login/")
    assert resp.status_code == 200

    resp = client.get("/accounts/signup/")
    assert resp.status_code == 200

    client.force_login(admin_user)
    resp = client.get("/")
    assert resp.status_code == 302

    resp = client.get("/", follow=True)
    assert (
        b"Your profile is not completed yet. Please complete your profile or skip it."
        in resp.content
    )

    Person.create(user=admin_user, is_completed=True)

    resp = client.get("/")
    assert resp.status_code == 200

    resp = client.get("/onboard")
    assert resp.status_code == 302


# def test_submit_task(client):
#     username, password = "tester", "p455w0rd"
#     user = User.objects.create_user(username=username, password=password)
#     client.force_login(user)
#     client.get("/test_task/TEST-MESSAGE")
#     assert tasks.run_next_task()


def test_profile(client, admin_user):

    username, password = "tester", "p455w0rd"
    user = User.objects.create_user(username=username, password=password)
    client.force_login(user)

    Ethnicity.objects.create(code="11111", description="New Zealand European")
    Ethnicity.objects.create(code="12411", description="Polish")
    Ethnicity.objects.create(code="12928", description="Latvian")
    assert not Person.objects.filter(user=user).exists()
    resp = client.get("/myprofile", follow=True)
    assert b"Next" in resp.content

    p = Person.create(user=user)
    resp = client.get("/myprofile", follow=True)
    assert b"Primary Language Spoken" in resp.content
    assert b"Edit" in resp.content
    p = Person.get(user=user)
    assert p.gender == 0 and p.ethnicities.count() == 0

    resp = client.post(
        "/profile/~update",
        dict(
            gender=1,
            date_of_birth="1969-01-01",
            ethnicities=["11111"],
            education_level="7",
            employment_status="3",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    assert b"Please read and consent to the Privacy Policy" in resp.content

    models.IwiGroup.create(
        code="1111",
        description="TEST",
        parent_code="11",
        parent_description="TEST",
        definition="TEST",
    )
    resp = client.post(
        "/profile/~update",
        dict(
            gender=1,
            date_of_birth="1969-01-01",
            ethnicities=["11111"],
            iwi_groups=["1111"],
            education_level="7",
            employment_status="3",
            is_accepted=True,
        ),
        follow=True,
    )
    assert resp.status_code == 200
    p = Person.get(user=user)
    assert p.gender == 1 and p.ethnicities.count() == 1

    client.force_login(admin_user)
    resp = client.get(f"/profiles/{user.profile.pk}")
    assert resp.status_code == 200
    resp = client.get(f"/profiles/{user.pk}")
    assert resp.status_code == 404

    resp = client.post(
        "/profile/~create",
        dict(
            gender=1,
            date_of_birth="1969-01-01",
            ethnicities=["11111"],
            education_level="7",
            employment_status="3",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    assert Person.objects.filter(user=admin_user).count() == 0
    assert b"consent" in resp.content

    resp = client.post(
        "/profile/~create",
        dict(
            gender=1,
            date_of_birth="1969-01-01",
            ethnicities=["11111"],
            education_level="7",
            employment_status="3",
            is_accepted=True,
        ),
        follow=True,
    )
    assert resp.status_code == 200
    assert admin_user.profile.ethnicities.count() == 1

    resp = client.post(
        "/profile/~update",
        dict(
            gender=2,
            date_of_birth="1969-01-01",
            ethnicities=["11111", "12411", "12928"],
            education_level="7",
            employment_status="3",
            is_accepted=True,
        ),
        follow=True,
    )
    assert resp.status_code == 200
    assert b"Position" in resp.content

    # Employments:
    org = models.Organisation.create(name="ORG")
    resp = client.get("/profile/employments/")
    assert not models.Affiliation.where(type="EMP", profile=p).exists()
    resp = client.post(
        "/profile/employments/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-profile": p.id,
            "form-0-org": org.id,
            "form-0-type": "EMP",
            "form-0-role": "ROLE",
            "form-0-start_date": "2020-05-02",
            "form-0-end_date": "",
            "form-0-id": "",
            "save": "Save",
        },
        follow=True,
    )
    assert models.Affiliation.where(type="EMP", profile=p).exists()

    p = admin_user.profile
    assert p.gender == 1 and p.ethnicities.count() == 3
    assert p.ethnicities.count() == 3

    # Create and update career stages
    models.CareerStage.create(code="R1", description="description #1", definition="definition #1")
    resp = client.get("/profile/career-stages/")
    assert not models.PersonCareerStage.where(profile=p).exists()
    resp = client.post(
        "/profile/career-stages/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-profile": p.id,
            "form-0-year_achieved": 2000,
            "form-0-career_stage": "R1",
            "form-0-id": "",
            "save": "Save",
        },
        follow=True,
    )
    assert models.PersonCareerStage.where(profile=p).exists()

    pcs = models.PersonCareerStage.get(profile=p)
    resp = client.post(
        "/profile/career-stages/",
        {
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 1,
            "form-0-profile": p.id,
            "form-0-year_achieved": 2003,
            "form-0-career_stage": "R1",
            "form-0-id": pcs.id,
            "form-1-profile": p.id,
            "form-1-year_achieved": "",
            "form-1-career_stage": "",
            "form-1-id": "",
            "next": "Next",
        },
        follow=True,
    )
    assert models.PersonCareerStage.where(profile=p, year_achieved=2003).exists()

    resp = client.post(
        "/profile/career-stages/",
        {
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 1,
            "form-0-profile": p.id,
            "form-0-year_achieved": 2003,
            "form-0-career_stage": "R1",
            "form-0-id": pcs.id,
            "form-0-DELETE": "on",
            "form-1-profile": p.id,
            "form-1-year_achieved": "",
            "form-1-career_stage": "",
            "form-1-id": "",
            "next": "Next",
        },
        follow=True,
    )
    assert not models.PersonCareerStage.where(profile=p, year_achieved=2003).exists()

    # Person identifier:
    models.PersonIdentifierType.create(
        code="11", description="Identifier #11", definition="Identifier #11 definition"
    )
    resp = client.get("/profile/external-ids/")
    assert not models.PersonPersonIdentifier.where(profile=p).exists()
    # resp = client.post(
    #     "/profile/external-ids/",
    #     {
    #         "form-TOTAL_FORMS": 1,
    #         "form-INITIAL_FORMS": 0,
    #         "form-0-profile": p.id,
    #         "form-0-code": 11,
    #         "form-0-value": "CODE 11",
    #         "form-0-id": "",
    #         "save": "Save",
    #     },
    #     follow=True,
    # )
    # assert models.PersonPersonIdentifier.where(profile=p).exists()

    resp = client.post(
        "/profile/cvs/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-id": "",
            "form-0-profile": p.id,
            "form-0-owner": admin_user.id,
            "form-0-title": "TEST",
            "form-0-file": BytesIO(b"TEST"),
            "next": "Next",
        },
        follow=True,
    )
    assert resp.status_code == 200

    # Accademic records:
    models.FieldOfStudy.create(
        code="180101",
        description="test",
        four_digit_code="1010",
        four_digit_description="test",
        two_digit_code="11",
        two_digit_description="test #11",
        definition="test definition",
    )
    resp = client.get("/profile/academic-records/")
    assert not models.AcademicRecord.where(profile=p).exists()
    resp = client.post(
        "/profile/academic-records/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-profile": p.id,
            "form-0-start_year": 2020,
            "form-0-qualification": 9,
            "form-0-conferred_on": "2020-05-02",
            "form-0-discipline": "180101",
            "form-0-awarded_by": org.id,
            "form-0-research_topic": "TOPIC",
            "form-0-id": "",
            "next": "Next",
        },
        follow=True,
    )
    # assert models.AcademicRecord.where(profile=p).exists()

    # Recognitions:
    a = models.Award.create(name="AWARD")
    resp = client.get("/profile/recognitions/")
    assert not models.Recognition.where(profile=p).exists()
    resp = client.post(
        "/profile/recognitions/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-profile": p.id,
            "form-0-recognized_in": 2020,
            "form-0-award": a.id,
            "form-0-awarded_by": org.id,
            "form-0-amount": "9999.99",
            "form-0-id": "",
            "next": "Next",
        },
        follow=True,
    )
    assert models.Recognition.where(profile=p).exists()

    # Comleted project
    resp = client.get(f"/profiles/{user.pk}")

    assert b"Female" in resp.content
    assert b"Latvian" in resp.content


def test_sentry(client, admin_user):

    client.post("/accounts/logout/")
    with pytest.raises(Exception) as excinfo:
        client.get("/sentry-debug/")
    assert "FAILURE" in str(excinfo.value)

    with pytest.raises(Exception) as excinfo:
        client.get("/sentry-debug/TEST")
    assert "TEST" in str(excinfo.value)

    client.force_login(admin_user)
    with pytest.raises(Exception) as excinfo:
        client.get("/sentry-debug-login/")
    assert "FAILURE" in str(excinfo.value)

    with pytest.raises(Exception) as excinfo:
        client.get("/sentry-debug-login/TEST123ABC")
    assert "TEST123ABC" in str(excinfo.value)


def test_subscription(client):

    resp = client.get("/", follow=True)
    assert b"Sign up for our newsletter" in resp.content

    assert not Subscription.objects.filter(email="test@test.com", name="Tester Testeron").exists()
    resp = client.post(
        "/subscribe/", dict(email="test@test.com", name="Tester Testeron"), follow=True
    )
    assert b"Verify Your E-mail Address" in resp.content
    assert Subscription.objects.filter(email="test@test.com", name="Tester Testeron").exists()

    resp = client.post("/subscribe/", dict(email="test123@test.com"))
    assert str(Subscription.objects.filter(email="test123@test.com").first()) == "test123@test.com"

    resp = client.post("/subscribe/", dict(email="test42@test.com", name="Tester"))
    assert str(Subscription.objects.filter(email="test42@test.com").first()) == "Tester"


def test_application(client, django_user_model):

    r = models.Round.get(title="Science Communication Prize 2021")
    u = django_user_model.objects.create(
        first_name="FN123",
        last_name="LN123",
        username="test123",
        password="p455w0rd",
        email="test123@test.com",
    )
    client.force_login(u)
    Person.create(user=u)
    org = models.Organisation.create(name="ORG")

    resp = client.get(f"/applications/{r.pk}/~create")
    assert resp.status_code == 200
    assert b"FN123" in resp.content
    assert b"LN123" in resp.content
    assert b"test123@test.com" in resp.content

    resp = client.post(
        f"/applications/{r.pk}/~create",
        dict(
            title="MR",
            first_name=u.first_name,
            last_name=u.last_name,
            org=org.id,
            position="POS",
            postal_address="123 Test Street",
            city="Auckland",
            postcode="1010",
            daytime_phone="0221221442",
            mobile_phone="0221221442",
            email=u.email,
        ),
        follow=True,
    )

    assert models.Application.where(email=u.email).exists()


def test_org_autocompleting(client, user):

    models.Organisation.create(name="ORG")
    resp = client.get("/autocomplete/org/?q=OR", follow=True)
    assert b"Sign in" in resp.content

    client.force_login(user)
    resp = client.get("/autocomplete/org/")
    assert resp.status_code == 200
    assert b"ORG" in resp.content

    resp = client.get("/autocomplete/org/?q=OR")
    assert resp.status_code == 200
    assert b"ORG" in resp.content

    # if query is not given select last
    for i in range(1, 20):
        models.Organisation.create(name=f"ABC #{i}")

    resp = client.get("/autocomplete/org/")
    assert resp.status_code == 200
    assert b"ORG" not in resp.content


def test_award_autocompleting(client, user):

    models.Award.create(name="AWARD")
    resp = client.get("/autocomplete/award/?q=AW", follow=True)
    assert b"Sign in" in resp.content

    client.force_login(user)
    resp = client.get("/autocomplete/award/")
    assert resp.status_code == 200
    assert b"AWARD" in resp.content

    resp = client.get("/autocomplete/award/?q=AW", follow=True)
    assert resp.status_code == 200
    assert b"AWARD" in resp.content

    # if query is not given select last
    for i in range(1, 20):
        models.Award.create(name=f"ABC #{i}")

    resp = client.get("/autocomplete/award/")
    assert resp.status_code == 200
    assert b"AWARD" not in resp.content


def test_invitation(client, admin_user):

    client.force_login(admin_user)
    org = models.Organisation.create(name="ORG")

    resp = client.get("/invitations/~create")
    assert resp.status_code == 200
    email = "test@test.net"

    resp = client.post(
        "/invitations/~create",
        dict(email=email, first_name="FN", last_name="LN"),
        follow=True,
    )
    assert resp.status_code == 200
    assert (f"An invitation was sent to {email}").encode() in resp.content

    assert models.Invitation.where(email=email).exists()

    resp = client.post(
        "/invitations/~create",
        dict(email=email, first_name="FN", last_name="LN", org=org.id),
        follow=True,
    )
    assert resp.status_code == 200
    assert (f"An invitation was sent to {email}").encode() in resp.content
    assert models.Invitation.where(org=org).exists()


def test_cv(client, admin_user):

    resp = client.get("/profile/cvs/")
    assert resp.status_code == 302

    client.force_login(admin_user)

    resp = client.post(
        "/profile/cvs/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-id": "",
            "form-0-title": "TEST",
            "form-0-file": BytesIO(b"TEST"),
            "save": "Save",
        },
        follow=True,
    )
    assert b"Please complete your profile" in resp.content

    profile = models.Person.create(user=admin_user, is_completed=True)

    resp = client.get("/profile/cvs/")

    resp = client.post(
        "/profile/cvs/",
        {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-0-id": "",
            "form-0-profile": profile.id,
            "form-0-owner": admin_user.id,
            "form-0-title": "TEST",
            "form-0-file": BytesIO(b"TEST"),
            "save": "Save",
        },
        follow=True,
    )

    assert resp.status_code == 200
    assert models.CurriculumVitae.where(owner=admin_user, profile=profile).exists()
