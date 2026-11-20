from dataclasses import asdict

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Booking
from .serializers import BookingCreateSerializer, BookingSerializer, QuoteSerializer


class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     viewsets.GenericViewSet):
    """
    GET  /api/bookings/                         → my bookings (owners also see their hotels' bookings)
    POST /api/bookings/                         → create a booking (price computed server-side)
    GET  /api/bookings/{id}/
    POST /api/bookings/{id}/cancel/
    POST /api/bookings/quote/                   → price breakdown without booking (public)
    GET  /api/bookings/lookup/?ref=LUM-123456&email=guest@example.com   (public)
    """

    permission_classes = [permissions.IsAuthenticated]
    lookup_value_regex = r'\d+'
    filterset_fields = ['status']
    ordering_fields = ['created_at', 'check_in']

    def get_queryset(self):
        qs = Booking.objects.select_related('hotel', 'room')
        user = self.request.user
        if user.is_staff or user.role == 'admin':
            return qs
        return qs.filter(Q(user=user) | Q(hotel__owner=user))

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == 'create' else BookingSerializer

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        if booking.user_id != request.user.id and not (request.user.is_staff or request.user.role == 'admin'):
            return Response({'detail': 'Only the guest who made this booking can cancel it.'},
                            status=status.HTTP_403_FORBIDDEN)
        if booking.status != Booking.Status.CONFIRMED:
            return Response({'detail': f'Booking is already {booking.status.lower()}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if booking.check_in <= timezone.localdate():
            return Response({'detail': 'Bookings can only be canceled before the check-in date.'},
                            status=status.HTTP_400_BAD_REQUEST)
        booking.status = Booking.Status.CANCELED
        booking.save(update_fields=['status', 'updated_at'])
        return Response(BookingSerializer(booking).data)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def quote(self, request):
        serializer = QuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(asdict(serializer.price()))

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def lookup(self, request):
        ref = request.query_params.get('ref', '').strip().upper()
        email = request.query_params.get('email', '').strip()
        if not ref or not email:
            return Response({'detail': 'Both ref and email are required.'}, status=status.HTTP_400_BAD_REQUEST)
        booking = get_object_or_404(
            Booking.objects.select_related('hotel', 'room'), booking_ref=ref, guest_email__iexact=email
        )
        return Response(BookingSerializer(booking).data)
