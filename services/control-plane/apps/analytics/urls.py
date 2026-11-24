from rest_framework.routers import DefaultRouter

from apps.analytics.views.trends import StackTrendDailyViewSet

router = DefaultRouter()
router.register("trends", StackTrendDailyViewSet, basename="stack-trend")

urlpatterns = router.urls
