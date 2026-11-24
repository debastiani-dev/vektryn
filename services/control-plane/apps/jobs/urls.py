from rest_framework.routers import DefaultRouter

from apps.jobs.views.jobs import JobPostingViewSet

router = DefaultRouter()
router.register("", JobPostingViewSet, basename="job-posting")

urlpatterns = router.urls
