from rest_framework.routers import DefaultRouter

from apps.base.views.notifications import NotificationViewSet

router = DefaultRouter()
router.register("", NotificationViewSet, basename="notifications")

urlpatterns = router.urls
