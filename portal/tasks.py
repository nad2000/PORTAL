from background_task import background
from background_task.tasks import logger
from django.contrib.auth import get_user_model

User = get_user_model()


@background()
def notify_user(user_id, message):
    # lookup user by id and send them a message
    user = User.objects.get(pk=user_id)
    user.email_user("Here is a notification", message or "You have been notified")
    logger.info(f"*** Message '{message}' was sent to address {user.email}")


# vim:set ft=python.django:
