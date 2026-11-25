from django.contrib import admin
from django.http import JsonResponse, HttpResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.analytics.views.system import (
    system_status_view,
    trigger_collector_sync_view,
)
from apps.base.views.auth import (
    csrf_cookie_view,
    current_user_view,
    login_view,
    logout_view,
)


def healthcheck(_request):
    return JsonResponse({"status": "ok", "service": "control-plane"})


def metrics_view(_request):
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("metrics", metrics_view, name="metrics-noslash"),
    path("metrics/", metrics_view, name="metrics"),
    path("api/v1/health/", healthcheck, name="api-healthcheck"),
    path("api/v1/auth/csrf/", csrf_cookie_view, name="api-auth-csrf"),
    path("api/v1/auth/login/", login_view, name="api-auth-login"),
    path("api/v1/auth/logout/", logout_view, name="api-auth-logout"),
    path("api/v1/auth/me/", current_user_view, name="api-auth-me"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/v1/resumes/", include("apps.resumes.urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/matches/", include("apps.matching.urls")),
    path("api/v1/leads/", include("apps.tracker.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/system/status/", system_status_view, name="api-system-status"),
    path(
        "api/v1/system/collect/",
        trigger_collector_sync_view,
        name="api-system-collect",
    ),
]
