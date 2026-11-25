from rest_framework.routers import DefaultRouter

from apps.jobs.views.jobs import JobPostingViewSet
from apps.jobs.views.saved_filters import SavedFilterViewSet
from apps.jobs.views.triage import DismissedJobViewSet, MutedCompanyViewSet

router = DefaultRouter()
# Register named sub-resources BEFORE "" so they are never captured as a JobPosting uuid
router.register("filters", SavedFilterViewSet, basename="saved-filter")
router.register("dismissed", DismissedJobViewSet, basename="dismissed-job")
router.register("muted-companies", MutedCompanyViewSet, basename="muted-company")
router.register("", JobPostingViewSet, basename="job-posting")

urlpatterns = router.urls
