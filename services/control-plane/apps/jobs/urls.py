from rest_framework.routers import DefaultRouter

from apps.jobs.views.jobs import JobPostingViewSet
from apps.jobs.views.saved_filters import SavedFilterViewSet

router = DefaultRouter()
# Register "filters" BEFORE "" so /api/v1/jobs/filters/ is never captured as a JobPosting uuid
router.register("filters", SavedFilterViewSet, basename="saved-filter")
router.register("", JobPostingViewSet, basename="job-posting")

urlpatterns = router.urls
