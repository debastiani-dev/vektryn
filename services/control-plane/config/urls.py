from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.analytics.views.system import (
    system_dlq_dismiss_view,
    system_dlq_list_view,
    system_dlq_replay_view,
    system_status_view,
    trigger_collector_sync_view,
)
from apps.base.views.auth import (
    change_password_view,
    csrf_cookie_view,
    current_user_view,
    deactivate_account_view,
    login_view,
    logout_view,
    profile_view,
)


def healthcheck(_request):
    return JsonResponse({"status": "ok", "service": "control-plane"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("api/v1/health/", healthcheck, name="api-healthcheck"),
    path("api/v1/auth/csrf/", csrf_cookie_view, name="api-auth-csrf"),
    path("api/v1/auth/login/", login_view, name="api-auth-login"),
    path("api/v1/auth/logout/", logout_view, name="api-auth-logout"),
    path("api/v1/auth/me/", current_user_view, name="api-auth-me"),
    path("api/v1/auth/profile/", profile_view, name="api-auth-profile"),
    path(
        "api/v1/auth/change-password/",
        change_password_view,
        name="api-auth-change-password",
    ),
    path(
        "api/v1/auth/deactivate/",
        deactivate_account_view,
        name="api-auth-deactivate",
    ),
    path("api/v1/users/", include("apps.base.user_urls")),
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
    path("api/v1/notifications/", include("apps.base.urls")),
    path("api/v1/system/status/", system_status_view, name="api-system-status"),
    path(
        "api/v1/system/collect/",
        trigger_collector_sync_view,
        name="api-system-collect",
    ),
    path("api/v1/system/dlq/", system_dlq_list_view, name="api-system-dlq"),
    path(
        "api/v1/system/dlq/replay/",
        system_dlq_replay_view,
        name="api-system-dlq-replay",
    ),
    path(
        "api/v1/system/dlq/dismiss/",
        system_dlq_dismiss_view,
        name="api-system-dlq-dismiss",
    ),
]
