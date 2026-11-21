import django_filters
from django.db import IntegrityError, transaction
from django.db.models import Avg, Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Hotel, Review, WishlistItem
from .serializers import HotelDetailSerializer, HotelSerializer, ReviewSerializer


class HotelPagination(PageNumberPagination):
    """Lets the frontend fetch the (now ~1,000-hotel) catalogue in a few requests."""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 500


class HotelFilter(django_filters.FilterSet):
    bookable = django_filters.BooleanFilter(method='filter_bookable')
    claimable = django_filters.BooleanFilter(method='filter_claimable')

    def filter_bookable(self, queryset, name, value):
        bookable = {'price_per_night__isnull': False, 'approval_status': Hotel.Approval.APPROVED}
        return queryset.filter(**bookable) if value else queryset.exclude(**bookable)

    def filter_claimable(self, queryset, name, value):
        claimable = {'source': Hotel.Source.OSM, 'owner__isnull': True}
        return queryset.filter(**claimable) if value else queryset.exclude(**claimable)

    city = django_filters.CharFilter(field_name='city', lookup_expr='iexact')
    max_price = django_filters.NumberFilter(field_name='price_per_night', lookup_expr='lte')
    min_price = django_filters.NumberFilter(field_name='price_per_night', lookup_expr='gte')
    min_match = django_filters.NumberFilter(field_name='match_score', lookup_expr='gte')
    min_rating = django_filters.NumberFilter(field_name='rating', lookup_expr='gte')

    class Meta:
        model = Hotel
        fields = ['city', 'featured']


class HotelViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/hotels/?city=Sylhet&max_price=8000&min_match=85&search=resort&ordering=price_per_night
    GET /api/hotels/{id}/
    GET /api/hotels/{id}/reviews/?traveler_type=Family
    POST /api/hotels/{id}/reviews/   (authenticated)
    """

    # Bookable hotels first, then imported listings; ?ordering= overrides
    queryset = (
        Hotel.objects.filter(is_active=True)
        .annotate(bookable_rank=Case(When(price_per_night__isnull=False, then=Value(1)), default=Value(0),
                                     output_field=IntegerField()))
        .order_by('-bookable_rank', '-featured', '-match_score', 'name')
        .prefetch_related('rooms', 'photos')
    )
    lookup_value_regex = r'\d+'
    filterset_class = HotelFilter
    pagination_class = HotelPagination
    search_fields = ['name', 'city', 'location', 'description']
    ordering_fields = ['price_per_night', 'rating', 'match_score', 'reviews_count']

    def get_serializer_class(self):
        return HotelDetailSerializer if self.action == 'retrieve' else HotelSerializer

    @action(detail=True, methods=['get', 'post'], serializer_class=ReviewSerializer,
            permission_classes=[permissions.IsAuthenticatedOrReadOnly])
    def reviews(self, request, pk=None):
        hotel = self.get_object()

        if request.method == 'GET':
            reviews = hotel.reviews.filter(is_flagged=False)
            traveler_type = request.query_params.get('traveler_type')
            if traveler_type:
                reviews = reviews.filter(traveler_type=traveler_type)
            page = self.paginate_queryset(reviews)
            return self.get_paginated_response(ReviewSerializer(page, many=True).data)

        user = request.user
        already_reviewed = Response({'detail': "You've already reviewed this hotel."}, status=status.HTTP_400_BAD_REQUEST)
        if hotel.reviews.filter(user=user).exists():
            return already_reviewed
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # The unique constraint catches two submissions racing past the check above
            with transaction.atomic():
                serializer.save(hotel=hotel, user=user, author_name=user.get_full_name() or user.email.split('@')[0])
        except IntegrityError:
            return already_reviewed

        # Keep the denormalised rating/count on the hotel in sync
        stats = hotel.reviews.filter(is_flagged=False).aggregate(avg=Avg('rating'), count=Count('id'))
        hotel.rating = round(stats['avg'] or 0, 1)
        hotel.reviews_count = max(hotel.reviews_count, stats['count'])
        hotel.save(update_fields=['rating', 'reviews_count'])

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WishlistViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    GET    /api/wishlist/             → saved hotels
    POST   /api/wishlist/  {hotelId}  → add (idempotent)
    DELETE /api/wishlist/{hotelId}/   → remove
    """

    serializer_class = HotelSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        return Hotel.objects.filter(wishlisted_by__user=self.request.user, is_active=True).prefetch_related('rooms', 'photos')

    def create(self, request):
        hotel_id = str(request.data.get('hotelId', ''))
        if not hotel_id.isdigit():
            return Response({'hotelId': 'A numeric hotel id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        hotel = get_object_or_404(Hotel, pk=hotel_id, is_active=True)
        try:
            _, created = WishlistItem.objects.get_or_create(user=request.user, hotel=hotel)
        except IntegrityError:
            created = False
        return Response({'hotelId': str(hotel.pk), 'saved': True},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def destroy(self, request, pk=None):
        WishlistItem.objects.filter(user=request.user, hotel_id=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
