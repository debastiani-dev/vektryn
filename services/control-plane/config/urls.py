from django.contrib import admin
from django.http import JsonResponse, HttpResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


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
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/resumes/", include("apps.resumes.urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/matches/", include("apps.matching.urls")),
    path("api/v1/leads/", include("apps.tracker.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
]