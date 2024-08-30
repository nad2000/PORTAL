import pytest
from django.test import RequestFactory

from portal.models import Person
from users.models import User
from users.views import UserRedirectView, UserUpdateView

pytestmark = pytest.mark.django_db


class TestUserUpdateView:
    """
    TODO:
        extracting view initialization code as class-scoped fixture
        would be great if only pytest-django supported non-function-scoped
        fixture db access -- this is a work-in-progress for now:
        https://github.com/pytest-dev/pytest-django/pull/258
    """

    def test_get_success_url(self, user: User, request_factory: RequestFactory):
        view = UserUpdateView()
        request = request_factory.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_success_url() == f"/users/{user.username}/"

    def test_get_object(self, user: User, request_factory: RequestFactory):
        view = UserUpdateView()
        request = request_factory.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user


class TestUserRedirectView:
    def test_get_redirect_url(self, user: User, request_factory: RequestFactory):
        view = UserRedirectView()
        request = request_factory.get("/fake-url")
        request.user = user

        view.request = request

        assert view.get_redirect_url() == f"/users/{user.username}/"


def test_adapter(client):

    username, password = "tester", "p455w0rd"
    user = User.objects.create_user(
        username=username, password=password, email="test@test.com", is_active=True
    )
    resp = client.post("/accounts/login/", dict(login=username, password=password), follow=True)
    resp = client.get("/", follow=True)
    # assert b"Your profile is not completed yet. Please complete your profile." in resp.content
    assert b"Please complete your profile" in resp.content

    p = Person.objects.create(user=user, is_accepted=True)
    p.is_completed = True
    p.save()

    client.post("/accounts/logout/", follow=True)
    resp = client.post("/accounts/login/", dict(login=username, password=password), follow=True)
    assert b"Please complete your profile" not in resp.content
