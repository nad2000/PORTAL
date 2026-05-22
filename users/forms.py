from allauth.account import forms as allauth_forms
from captcha.fields import ReCaptchaField
from dal import autocomplete
from django.conf import settings
from django.contrib.auth import forms, get_user_model
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class UserChangeForm(forms.UserChangeForm):
    class Meta(forms.UserChangeForm.Meta):
        model = User
        widgets = {
            "title": autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
        }


class UserCreationForm(forms.UserCreationForm):
    error_message = forms.UserCreationForm.error_messages.update(
        {"duplicate_username": _("This username has already been taken.")}
    )

    class Meta(forms.UserCreationForm.Meta):
        model = User

    def clean_username(self):
        username = self.cleaned_data["username"]

        try:
            User.objects.get(username=username)
        except User.DoesNotExist:
            return username

        raise ValidationError(self.error_messages["duplicate_username"])


class UserSignupForm(allauth_forms.SignupForm):
    initial = {
        "password1": "",
        "password2": "",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.DEBUG:
            self.fields["captcha"] = ReCaptchaField()

    # class Meta(allauth_forms.SignupForm.Meta):
    class Meta:
        exclude = ["registered_on"]


# class UserLoginForm(allauth_forms.LoginForm):
#     captcha = ReCaptchaField()
