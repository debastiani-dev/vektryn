from rest_framework.routers import DefaultRouter

from apps.base.views.users import StaffUserViewSet

router = DefaultRouter()
router.register("", StaffUserViewSet, basename="staff-users")

urlpatterns = router.urls
