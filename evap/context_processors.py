import random

from django.conf import settings
from django.utils.translation import get_language


def slogan(request):
    if get_language() == "de":
        return {"slogan": random.choice(settings.SLOGANS_DE)}  # nosec
    return {"slogan": random.choice(settings.SLOGANS_EN)}  # nosec


def debug(request):
    return {"debug": settings.DEBUG}


def allow_anonymous_feedback_messages(request):
    return {"allow_anonymous_feedback_messages": settings.ALLOW_ANONYMOUS_FEEDBACK_MESSAGES}
