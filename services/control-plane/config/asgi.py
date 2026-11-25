import os

from django.core.asgi import get_asgi_application

from config.telemetry import configure_sentry

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
configure_sentry()
application = get_asgi_application()
