from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def healthcheck(_request):
    return JsonResponse({"status": "ok", "service": "control-plane"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("api/v1/health/", healthcheck, name="api-healthcheck"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/resumes/", include("apps.resumes.urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/matches/", include("apps.matching.urls")),
    path("api/v1/leads/", include("apps.tracker.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
]