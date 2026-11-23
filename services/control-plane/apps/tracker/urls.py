from rest_framework.routers import DefaultRouter

from apps.tracker.views.leads import ApplicationLeadViewSet

router = DefaultRouter()
router.register("", ApplicationLeadViewSet, basename="application-lead")

urlpatterns = router.urls