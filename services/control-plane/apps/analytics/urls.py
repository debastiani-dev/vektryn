from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.analytics.views.personal import personal_analytics_view
from apps.analytics.views.trends import StackTrendDailyViewSet

router = DefaultRouter()
router.register("trends", StackTrendDailyViewSet, basename="stack-trend")

urlpatterns = [
    path("personal/", personal_analytics_view, name="personal-analytics"),
    *router.urls,
]
