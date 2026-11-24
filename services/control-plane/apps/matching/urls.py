from rest_framework.routers import DefaultRouter

from apps.matching.views.matching import MatchScoreViewSet

router = DefaultRouter()
router.register("", MatchScoreViewSet, basename="match-score")

urlpatterns = router.urls
