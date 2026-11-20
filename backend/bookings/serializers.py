import re

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from hotels.models import Room

from .models import Booking
from .pricing import ADDON_PRICES, COUPONS, calculate_price

MAX_NIGHTS = 30
BD_MOBILE_RE = re.compile(r'^01[3-9]\d{8}$')


def mask_mobile(number: str) -> str:
    return f'{number[:3]}{"*" * 6}{number[-2:]}'


class QuoteSerializer(serializers.Serializer):
    """Validates a stay and prices it. Used by /quote/ and as the base for booking creation."""

    roomId = serializers.PrimaryKeyRelatedField(
        source='room', queryset=Room.objects.select_related('hotel').filter(hotel__is_active=True)
    )
    checkIn = serializers.DateField(source='check_in')
    checkOut = serializers.DateField(source='check_out')
    adults = serializers.IntegerField(min_value=1, max_value=20, default=2)
    roomCount = serializers.IntegerField(source='room_count', min_value=1, max_value=10, default=1)
    addons = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(ADDON_PRICES)), required=False, default=list
    )
    coupon = serializers.CharField(source='coupon_code', required=False, allow_blank=True, default='')

    def validate_coupon(self, value):
        if value and value.strip().upper() not in COUPONS:
            raise serializers.ValidationError('Invalid coupon code.')
        return value.strip().upper()

    def validate(self, attrs):
        check_in, check_out = attrs['check_in'], attrs['check_out']
        if check_in < timezone.localdate():
            raise serializers.ValidationError({'checkIn': 'Check-in cannot be in the past.'})
        if check_out <= check_in:
            raise serializers.ValidationError({'checkOut': 'Check-out must be after check-in.'})
        if (check_out - check_in).days > MAX_NIGHTS:
            raise serializers.ValidationError({'checkOut': f'Stays are limited to {MAX_NIGHTS} nights.'})

        room = attrs['room']
        if attrs['adults'] > room.capacity * attrs['room_count']:
            raise serializers.ValidationError(
                {'adults': f'{room.name} sleeps {room.capacity} per room; add more rooms for {attrs["adults"]} adults.'}
            )
        attrs['addons'] = sorted(set(attrs.get('addons', [])))
        return attrs

    def price(self):
        data = self.validated_data
        return calculate_price(
            price_per_night=data['room'].price_per_night,
            nights=(data['check_out'] - data['check_in']).days,
            room_count=data['room_count'],
            addons=data['addons'],
            coupon=data['coupon_code'],
        )


class BookingCreateSerializer(QuoteSerializer):
    guestName = serializers.CharField(source='guest_name', max_length=120)
    guestEmail = serializers.EmailField(source='guest_email')
    guestPhone = serializers.CharField(source='guest_phone', max_length=20)
    specialRequest = serializers.CharField(source='special_request', required=False, allow_blank=True, default='')
    paymentMethod = serializers.ChoiceField(source='payment_method', choices=Booking.PaymentMethod.choices)
    paymentAccount = serializers.CharField(source='payment_account', required=False, allow_blank=True, default='')

    def validate(self, attrs):
        attrs = super().validate(attrs)
        method = attrs['payment_method']
        if method in (Booking.PaymentMethod.BKASH, Booking.PaymentMethod.NAGAD):
            number = re.sub(r'[\s-]', '', attrs.get('payment_account', '')).removeprefix('+88')
            if not BD_MOBILE_RE.match(number):
                raise serializers.ValidationError({'paymentAccount': 'Enter a valid 11-digit Bangladeshi mobile number.'})
            attrs['payment_account'] = mask_mobile(number)
        else:
            attrs['payment_account'] = ''
        return attrs

    def create(self, validated_data):
        data = dict(validated_data)
        with transaction.atomic():
            # Lock the room row so concurrent bookings can't both take the last unit
            room = Room.objects.select_for_update().select_related('hotel').get(pk=data.pop('room').pk)
            booked = Booking.units_booked(room, data['check_in'], data['check_out'])
            if booked + data['room_count'] > room.total_units:
                raise serializers.ValidationError({'roomId': f'{room.name} is not available for those dates.'})

            quote = self.price()
            fields = dict(
                **data,
                room=room,
                hotel=room.hotel,
                user=self.context['request'].user,
                room_total=quote.room_total,
                tax=quote.tax,
                addons_total=quote.addons_total,
                discount=quote.discount,
                total_price=quote.total,
            )
            # Booking refs are random; retry on the (rare) collision
            for attempt in range(5):
                try:
                    with transaction.atomic():
                        return Booking.objects.create(**fields)
                except IntegrityError:
                    if attempt == 4:
                        raise


class BookingSerializer(serializers.ModelSerializer):
    """Read shape — matches the frontend Booking type plus the price breakdown."""

    id = serializers.CharField(read_only=True)
    bookingRef = serializers.CharField(source='booking_ref')
    hotelId = serializers.CharField(source='hotel_id')
    hotelName = serializers.CharField(source='hotel.name')
    hotelImage = serializers.CharField(source='hotel.image')
    location = serializers.CharField(source='hotel.location')
    roomId = serializers.CharField(source='room_id')
    roomType = serializers.CharField(source='room.name')
    checkIn = serializers.DateField(source='check_in')
    checkOut = serializers.DateField(source='check_out')
    nights = serializers.IntegerField()
    guests = serializers.SerializerMethodField()
    roomCount = serializers.IntegerField(source='room_count')
    roomTotal = serializers.IntegerField(source='room_total')
    addonsTotal = serializers.IntegerField(source='addons_total')
    totalPrice = serializers.IntegerField(source='total_price')
    paymentMethod = serializers.SerializerMethodField()
    guestName = serializers.CharField(source='guest_name')
    guestEmail = serializers.EmailField(source='guest_email')
    guestPhone = serializers.CharField(source='guest_phone')
    specialRequest = serializers.CharField(source='special_request')
    createdAt = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'bookingRef', 'hotelId', 'hotelName', 'hotelImage', 'location', 'roomId', 'roomType',
            'checkIn', 'checkOut', 'nights', 'guests', 'adults', 'roomCount', 'addons',
            'roomTotal', 'tax', 'addonsTotal', 'discount', 'totalPrice', 'paymentMethod', 'status',
            'guestName', 'guestEmail', 'guestPhone', 'specialRequest', 'createdAt',
        ]

    def get_guests(self, obj):
        adults = f'{obj.adults} Adult{"s" if obj.adults != 1 else ""}'
        rooms = f'{obj.room_count} Room{"s" if obj.room_count != 1 else ""}'
        return f'{adults}, {rooms}'

    def get_paymentMethod(self, obj):
        labels = {
            Booking.PaymentMethod.CARD: 'Credit/Debit Card',
            Booking.PaymentMethod.PAY_AT_HOTEL: 'Pay at Hotel',
        }
        if obj.payment_method in labels:
            return labels[obj.payment_method]
        return f'{obj.payment_method} ({obj.payment_account})'

    def get_createdAt(self, obj):
        return timezone.localtime(obj.created_at).date().isoformat()
