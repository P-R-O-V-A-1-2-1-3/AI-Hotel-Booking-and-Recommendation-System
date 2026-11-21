from rest_framework.routers import DefaultRouter

from .views import HotelViewSet, WishlistViewSet

router = DefaultRouter()
router.register('hotels', HotelViewSet, basename='hotel')
router.register('wishlist', WishlistViewSet, basename='wishlist')

urlpatterns = router.urls
