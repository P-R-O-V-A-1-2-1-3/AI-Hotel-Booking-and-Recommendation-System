from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from hotels.models import Hotel, Room

from .models import Booking
from .pricing import calculate_price

User = get_user_model()


class PricingTests(APITestCase):
    def test_matches_frontend_checkout(self):
        # Same stay the frontend Checkout showed as ৳17,172: 3 nights × 5,200 + 12% tax + transfer − 1,500
        quote = calculate_price(5200, nights=3, addons=['transfer'])
        self.assertEqual((quote.room_total, quote.tax, quote.addons_total, quote.total), (15600, 1872, 1200, 17172))

    def test_coupon_takes_ten_percent_off(self):
        self.assertEqual(calculate_price(5200, nights=3, addons=['transfer'], coupon='lumina20').total, 15455)


class BookingApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hotel = Hotel.objects.create(
            name='Sajek Cloud Retreat', city='Sajek Valley', location='Ruilui Para', description='Clouds',
            price_per_night=5200, image='https://example.com/a.jpg', latitude=23.38, longitude=92.29,
        )
        cls.room = Room.objects.create(hotel=cls.hotel, name='Cloud Cottage', price_per_night=5200, capacity=2,
                                       total_units=1)
        cls.guest = User.objects.create_user(email='guest@example.com', password='S3cure-pass-77')
        cls.other = User.objects.create_user(email='other@example.com', password='S3cure-pass-77')

    def payload(self, **overrides):
        start = timezone.localdate() + timedelta(days=14)
        data = {
            'roomId': self.room.pk,
            'checkIn': start.isoformat(),
            'checkOut': (start + timedelta(days=3)).isoformat(),
            'adults': 2,
            'addons': ['transfer'],
            'guestName': 'Nadia Rahman',
            'guestEmail': 'nadia@example.com',
            'guestPhone': '+880 1712-345678',
            'paymentMethod': 'bKash',
            'paymentAccount': '01712345678',
            'totalPrice': 1,  # client-sent totals must be ignored
        }
        data.update(overrides)
        return data

    def test_create_requires_auth_and_prices_server_side(self):
        self.assertEqual(self.client.post('/api/bookings/', self.payload(), format='json').status_code, 401)

        self.client.force_authenticate(self.guest)
        res = self.client.post('/api/bookings/', self.payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res.data['totalPrice'], 17172)
        self.assertEqual(res.data['nights'], 3)
        self.assertEqual(res.data['paymentMethod'], 'bKash (017******78)')
        self.assertRegex(res.data['bookingRef'], r'^LUM-\d{6}$')

    def test_validation(self):
        self.client.force_authenticate(self.guest)
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        cases = [
            self.payload(checkIn=past),
            self.payload(checkOut=self.payload()['checkIn']),
            self.payload(adults=5),
            self.payload(addons=['helicopter']),
            self.payload(paymentAccount='12345'),
            self.payload(coupon='FREESTAY'),
        ]
        for case in cases:
            self.assertEqual(self.client.post('/api/bookings/', case, format='json').status_code, 400, case)

    def test_room_cannot_be_double_booked(self):
        self.client.force_authenticate(self.guest)
        self.assertEqual(self.client.post('/api/bookings/', self.payload(), format='json').status_code, 201)

        # Overlapping stay on the only unit is rejected
        start = timezone.localdate() + timedelta(days=15)
        overlap = self.payload(checkIn=start.isoformat(), checkOut=(start + timedelta(days=2)).isoformat())
        res = self.client.post('/api/bookings/', overlap, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('roomId', res.data)

        # Back-to-back stay (check-in on the previous check-out day) is fine
        after = timezone.localdate() + timedelta(days=17)
        back_to_back = self.payload(checkIn=after.isoformat(), checkOut=(after + timedelta(days=1)).isoformat())
        self.assertEqual(self.client.post('/api/bookings/', back_to_back, format='json').status_code, 201)

    def test_users_only_see_and_cancel_their_own_bookings(self):
        self.client.force_authenticate(self.guest)
        booking_id = self.client.post('/api/bookings/', self.payload(), format='json').data['id']

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/bookings/').data['count'], 0)
        self.assertEqual(self.client.post(f'/api/bookings/{booking_id}/cancel/').status_code, 404)

        self.client.force_authenticate(self.guest)
        res = self.client.post(f'/api/bookings/{booking_id}/cancel/')
        self.assertEqual(res.data['status'], 'Canceled')
        self.assertEqual(self.client.post(f'/api/bookings/{booking_id}/cancel/').status_code, 400)

        # Canceled bookings free the room again
        self.assertEqual(self.client.post('/api/bookings/', self.payload(), format='json').status_code, 201)

    def test_quote_and_public_lookup(self):
        quote = self.client.post('/api/bookings/quote/', self.payload(), format='json')
        self.assertEqual(quote.status_code, status.HTTP_200_OK)
        self.assertEqual(quote.data['total'], 17172)

        self.client.force_authenticate(self.guest)
        ref = self.client.post('/api/bookings/', self.payload(), format='json').data['bookingRef']
        self.client.force_authenticate(None)

        self.assertEqual(self.client.get(f'/api/bookings/lookup/?ref={ref}').status_code, 400)
        self.assertEqual(self.client.get(f'/api/bookings/lookup/?ref={ref}&email=wrong@x.com').status_code, 404)
        res = self.client.get(f'/api/bookings/lookup/?ref={ref.lower()}&email=NADIA@example.com')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(Booking.objects.get(booking_ref=ref).hotel, self.hotel)
