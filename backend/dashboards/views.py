"""
Dashboard APIs for the three roles in the design mockups:

    /api/dashboard/me/           traveler overview (any signed-in user)
    /api/owner/overview/         hotel owner portal (role=owner, or admin)
    /api/admin/overview/         platform admin (role=admin or staff)
    /api/admin/...               approve hotels, moderate reviews, suspend users
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from bookings.serializers import BookingSerializer
from hotels.models import Hotel, HotelClaim, Review, WishlistItem

User = get_user_model()


def is_admin(user) -> bool:
    return user.is_authenticated and (user.is_staff or user.role == 'admin')


class IsHotelOwner(permissions.BasePermission):
    message = 'Only hotel owners can use the partner portal.'

    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.user.role == 'owner' or is_admin(request.user))


class IsPlatformAdmin(permissions.BasePermission):
    message = 'Admins only.'

    def has_permission(self, request, view):
        return is_admin(request.user)


def _nights_in_window(booking, start, end) -> int:
    """Room-nights of a booking that fall inside [start, end)."""
    overlap = (min(booking.check_out, end) - max(booking.check_in, start)).days
    return max(overlap, 0) * booking.room_count


def _review_json(review):
    return {
        'id': review.pk,
        'author': review.author_name,
        'rating': review.rating,
        'title': review.title,
        'comment': review.comment,
        'date': review.created_at.date().isoformat(),
    }


# ───────────────────────── Traveler ─────────────────────────

class MyDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        bookings = Booking.objects.filter(user=user).select_related('hotel', 'room')
        active = bookings.exclude(status=Booking.Status.CANCELED)
        upcoming = active.filter(status=Booking.Status.CONFIRMED, check_in__gte=today).order_by('check_in').first()

        return Response({
            'stats': {
                'trips': active.count(),
                'savedWithDeals': active.aggregate(total=Sum('discount'))['total'] or 0,
                'wishlisted': WishlistItem.objects.filter(user=user).count(),
                'reviewsWritten': Review.objects.filter(user=user).count(),
            },
            'upcoming': BookingSerializer(upcoming).data if upcoming else None,
            'recentBookings': BookingSerializer(bookings[:5], many=True).data,
        })


# ───────────────────────── Hotel owner ─────────────────────────

class OwnerOverviewView(APIView):
    permission_classes = [IsHotelOwner]

    def get(self, request):
        user = request.user
        hotels = Hotel.objects.all() if is_admin(user) else Hotel.objects.filter(owner=user)
        hotels = hotels.order_by('name')
        if not hotels.exists():
            return Response({'hotels': [], 'hotel': None})

        hotel_id = request.query_params.get('hotel')
        hotel = hotels.filter(pk=hotel_id).first() if hotel_id and hotel_id.isdigit() else None
        hotel = hotel or hotels.first()

        try:
            days = max(7, min(int(request.query_params.get('days', 30)), 365))
        except ValueError:
            days = 30
        today = timezone.localdate()
        # Window is the last `days` days including today: [start, end)
        start, end = today - timedelta(days=days - 1), today + timedelta(days=1)

        rooms = list(hotel.rooms.all())
        live = Booking.objects.filter(hotel=hotel).exclude(status=Booking.Status.CANCELED)
        stays = list(live.filter(check_in__lt=end, check_out__gt=start))

        # Revenue is counted on the check-in date; occupancy on room-nights inside the window
        revenue_by_day = {start + timedelta(days=i): 0 for i in range(days)}
        nights_by_room = {r.pk: 0 for r in rooms}
        for b in stays:
            if b.check_in in revenue_by_day:
                revenue_by_day[b.check_in] += b.total_price
            nights_by_room[b.room_id] = nights_by_room.get(b.room_id, 0) + _nights_in_window(b, start, end)
        capacity = sum(r.total_units for r in rooms) * days

        return Response({
            'hotels': [{'id': str(h.pk), 'name': h.name, 'isActive': h.is_active} for h in hotels],
            'hotel': {'id': str(hotel.pk), 'name': hotel.name, 'city': hotel.city, 'isActive': hotel.is_active},
            'days': days,
            'stats': {
                'revenue': sum(revenue_by_day.values()),
                'occupancyRate': round(100 * sum(nights_by_room.values()) / capacity) if capacity else 0,
                'bookings': live.filter(created_at__date__gte=start).count(),
                'rating': float(hotel.rating),
                'reviewsCount': hotel.reviews_count,
            },
            'revenueTrend': [{'date': d.isoformat(), 'amount': amount} for d, amount in revenue_by_day.items()],
            'occupancyByRoom': [
                {'room': r.name, 'nights': nights_by_room.get(r.pk, 0), 'capacity': r.total_units * days} for r in rooms
            ],
            'recentBookings': BookingSerializer(
                live.select_related('hotel', 'room').order_by('-created_at')[:5], many=True
            ).data,
            'recentReviews': [_review_json(r) for r in hotel.reviews.filter(is_flagged=False)[:5]],
            'rooms': [
                {
                    'id': r.pk, 'name': r.name, 'pricePerNight': r.price_per_night, 'originalPrice': r.original_price,
                    'totalUnits': r.total_units, 'capacity': r.capacity,
                }
                for r in rooms
            ],
        })


# ───────────────────────── Platform admin ─────────────────────────

class AdminOverviewView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        since = timezone.now() - timedelta(days=30)
        live = Booking.objects.exclude(status=Booking.Status.CANCELED)
        recent = live.filter(created_at__gte=since)
        six_months_ago = (timezone.localdate().replace(day=1) - timedelta(days=150)).replace(day=1)

        monthly = (
            live.filter(created_at__date__gte=six_months_ago)
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(bookings=Count('id'), gmv=Sum('total_price'))
            .order_by('month')
        )

        return Response({
            'stats': {
                'users': User.objects.count(),
                'hotels': Hotel.objects.filter(is_active=True, price_per_night__isnull=False).count(),
                'importedListings': Hotel.objects.filter(source=Hotel.Source.OSM, owner__isnull=True).count(),
                'gmv30': recent.aggregate(total=Sum('total_price'))['total'] or 0,
                'bookings30': recent.count(),
                'flaggedReviews': Review.objects.filter(is_flagged=True).count(),
            },
            'monthly': self._six_months(monthly, six_months_ago),
            'bookingsByCity': [
                {'city': city, 'count': count}
                for city, count in live.values('hotel__city').annotate(count=Count('id')).order_by('-count')
                .values_list('hotel__city', 'count')
            ],
            'pendingHotels': [
                {'id': h.pk, 'name': h.name, 'city': h.city, 'location': h.location,
                 'submitted': (h.submitted_at or h.created_at).date().isoformat(), 'image': h.cover_image(request),
                 'owner': h.owner.email if h.owner else None, 'rooms': h.rooms.count(), 'photos': h.photos.count(),
                 'fromPrice': h.price_per_night}
                for h in Hotel.objects.filter(approval_status=Hotel.Approval.PENDING)
                .select_related('owner').prefetch_related('photos').order_by('submitted_at', 'created_at')[:20]
            ],
            'pendingClaims': [
                {'id': c.pk, 'hotelId': str(c.hotel_id), 'hotelName': c.hotel.name, 'city': c.hotel.city,
                 'owner': c.user.email, 'message': c.message, 'created': c.created_at.date().isoformat()}
                for c in HotelClaim.objects.filter(status=HotelClaim.Status.PENDING)
                .select_related('hotel', 'user').order_by('created_at')[:20]
            ],
            'flaggedReviews': [
                {**_review_json(r), 'hotel': r.hotel.name}
                for r in Review.objects.filter(is_flagged=True).select_related('hotel')[:10]
            ],
            'recentUsers': [
                {
                    'id': u.pk, 'name': u.get_full_name() or u.email.split('@')[0], 'email': u.email,
                    'role': u.role, 'joined': u.date_joined.date().isoformat(), 'isActive': u.is_active,
                }
                for u in User.objects.order_by('-date_joined')[:8]
            ],
        })


    @staticmethod
    def _six_months(rows, first_month):
        """Every month from first_month to now, with zeros where nothing was booked."""
        by_month = {(r['month'].year, r['month'].month): r for r in rows}
        months, cursor = [], first_month
        for _ in range(6):
            row = by_month.get((cursor.year, cursor.month), {})
            months.append({'month': cursor.strftime('%b %Y'), 'bookings': row.get('bookings', 0), 'gmv': row.get('gmv') or 0})
            cursor = (cursor + timedelta(days=32)).replace(day=1)
        return months


class AdminHotelDecisionView(APIView):
    """POST {decision: 'approve'|'reject', note?} on a submitted hotel."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        hotel = get_object_or_404(Hotel, pk=pk)
        decision = request.data.get('decision', 'approve')
        note = str(request.data.get('note', '')).strip()[:1000]
        if decision == 'approve':
            hotel.approval_status, hotel.is_active, hotel.review_note = Hotel.Approval.APPROVED, True, note
        elif decision == 'reject':
            if not note:
                return Response({'note': 'Tell the owner what to fix.'}, status=status.HTTP_400_BAD_REQUEST)
            hotel.approval_status, hotel.is_active, hotel.review_note = Hotel.Approval.REJECTED, False, note
        else:
            return Response({'decision': 'Use "approve" or "reject".'}, status=status.HTTP_400_BAD_REQUEST)
        hotel.save(update_fields=['approval_status', 'is_active', 'review_note'])
        return Response({'id': hotel.pk, 'approvalStatus': hotel.approval_status, 'isActive': hotel.is_active})


class AdminClaimDecisionView(APIView):
    """POST {decision: 'approve'|'reject'} on an ownership claim for an imported listing."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        claim = get_object_or_404(HotelClaim.objects.select_related('hotel', 'user'), pk=pk)
        decision = request.data.get('decision')
        if claim.status != HotelClaim.Status.PENDING:
            return Response({'detail': f'This claim was already {claim.status}.'}, status=status.HTTP_400_BAD_REQUEST)
        if decision == 'approve':
            if claim.hotel.owner_id and claim.hotel.owner_id != claim.user_id:
                return Response({'detail': 'This hotel already has an owner.'}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                claim.hotel.owner = claim.user
                claim.hotel.save(update_fields=['owner'])
                claim.status = HotelClaim.Status.APPROVED
                claim.save(update_fields=['status'])
                # Only one owner per hotel: close the other pending claims for it
                HotelClaim.objects.filter(hotel=claim.hotel, status=HotelClaim.Status.PENDING)                     .exclude(pk=claim.pk).update(status=HotelClaim.Status.REJECTED)
        elif decision == 'reject':
            claim.status = HotelClaim.Status.REJECTED
            claim.save(update_fields=['status'])
        else:
            return Response({'decision': 'Use "approve" or "reject".'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': claim.pk, 'status': claim.status})


class AdminReviewView(APIView):
    """POST clears the flag (dismiss); DELETE removes the review."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk)
        review.is_flagged = False
        review.save(update_fields=['is_flagged'])
        return Response({'id': review.pk, 'isFlagged': False})

    def delete(self, request, pk):
        get_object_or_404(Review, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminUserStatusView(APIView):
    """POST {active: bool} — suspend or reactivate an account."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        if target.pk == request.user.pk:
            return Response({'detail': "You can't suspend your own account."}, status=status.HTTP_400_BAD_REQUEST)
        active = request.data.get('active')
        if not isinstance(active, bool):
            return Response({'active': 'Must be true or false.'}, status=status.HTTP_400_BAD_REQUEST)
        target.is_active = active
        target.save(update_fields=['is_active'])
        return Response({'id': target.pk, 'isActive': target.is_active})
