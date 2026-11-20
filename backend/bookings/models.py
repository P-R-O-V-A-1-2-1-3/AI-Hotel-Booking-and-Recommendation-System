import secrets

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from hotels.models import Hotel, Room


def generate_booking_ref() -> str:
    return f'LUM-{secrets.randbelow(900000) + 100000}'


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = 'Confirmed'
        COMPLETED = 'Completed'
        CANCELED = 'Canceled'

    class PaymentMethod(models.TextChoices):
        BKASH = 'bKash'
        NAGAD = 'Nagad'
        CARD = 'Card'
        PAY_AT_HOTEL = 'PayAtHotel'

    booking_ref = models.CharField(max_length=12, unique=True, default=generate_booking_ref, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='bookings')
    hotel = models.ForeignKey(Hotel, on_delete=models.PROTECT, related_name='bookings')
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='bookings')

    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveSmallIntegerField(default=2)
    room_count = models.PositiveSmallIntegerField(default=1)

    guest_name = models.CharField(max_length=120)
    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=20)
    special_request = models.TextField(blank=True)

    addons = models.JSONField(default=list, blank=True)
    coupon_code = models.CharField(max_length=30, blank=True)

    # Amounts in BDT, calculated server-side (see bookings/pricing.py)
    room_total = models.PositiveIntegerField()
    tax = models.PositiveIntegerField()
    addons_total = models.PositiveIntegerField(default=0)
    discount = models.PositiveIntegerField(default=0)
    total_price = models.PositiveIntegerField()

    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices)
    payment_account = models.CharField(max_length=20, blank=True, help_text='Masked MFS number')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=F('check_in')), name='booking_checkout_after_checkin'),
        ]

    def __str__(self):
        return f'{self.booking_ref} — {self.hotel.name}'

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @classmethod
    def units_booked(cls, room, check_in, check_out) -> int:
        """Rooms of this type already held by confirmed bookings overlapping [check_in, check_out)."""
        return (
            cls.objects.filter(
                room=room,
                status=cls.Status.CONFIRMED,
                check_in__lt=check_out,
                check_out__gt=check_in,
            ).aggregate(total=models.Sum('room_count'))['total']
            or 0
        )
