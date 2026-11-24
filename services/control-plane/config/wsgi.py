import os

from django.core.wsgi import get_wsgi_application

from config.telemetry import configure_telemetry

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
configure_telemetry()
application = get_wsgi_application()
