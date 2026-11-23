from rest_framework.routers import DefaultRouter

from apps.resumes.views.resumes import ResumeProfileViewSet

router = DefaultRouter()
router.register("", ResumeProfileViewSet, basename="resume-profile")

urlpatterns = router.urls