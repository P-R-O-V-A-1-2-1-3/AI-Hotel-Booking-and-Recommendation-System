from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Hotel, Room

User = get_user_model()


def make_hotel(name, city, price, **extra):
    hotel = Hotel.objects.create(
        name=name, city=city, location=f'Somewhere, {city}', description='Nice place', price_per_night=price,
        image='https://example.com/a.jpg', latitude=23.7, longitude=90.4, match_score=extra.pop('match_score', 90),
        **extra,
    )
    Room.objects.create(hotel=hotel, name=f'{name} Deluxe', price_per_night=price)
    return hotel


class HotelApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sylhet = make_hotel('Tea Resort', 'Sylhet', 6400, match_score=92)
        cls.dhaka = make_hotel('City Hotel', 'Dhaka', 14500, match_score=80)
        make_hotel('Hidden Hotel', 'Dhaka', 3000, is_active=False)
        cls.user = User.objects.create_user(email='t@example.com', password='S3cure-pass-77')

    def test_list_uses_frontend_field_names_and_hides_inactive(self):
        res = self.client.get('/api/hotels/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 2)
        hotel = res.data['results'][0]
        for key in ('pricePerNight', 'matchScore', 'reviewsCount', 'coordinates', 'roomType'):
            self.assertIn(key, hotel)
        self.assertIsInstance(hotel['id'], str)

    def test_filters(self):
        self.assertEqual(self.client.get('/api/hotels/?city=sylhet').data['count'], 1)
        self.assertEqual(self.client.get('/api/hotels/?max_price=10000').data['count'], 1)
        self.assertEqual(self.client.get('/api/hotels/?min_match=85').data['count'], 1)
        self.assertEqual(self.client.get('/api/hotels/?search=tea').data['count'], 1)

    def test_detail_includes_rooms_and_bad_ids_404(self):
        res = self.client.get(f'/api/hotels/{self.sylhet.pk}/')
        self.assertEqual(res.data['rooms'][0]['name'], 'Tea Resort Deluxe')
        self.assertEqual(self.client.get('/api/hotels/99999/').status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get('/api/hotels/abc/').status_code, status.HTTP_404_NOT_FOUND)

    def test_reviews_require_auth_to_post_and_update_rating(self):
        url = f'/api/hotels/{self.sylhet.pk}/reviews/'
        payload = {'rating': 4, 'travelerType': 'Solo', 'title': 'Good', 'comment': 'Quiet and clean.'}
        self.assertEqual(self.client.post(url, payload, format='json').status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.user)
        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.client.get(url).data['count'], 1)
        self.sylhet.refresh_from_db()
        self.assertEqual(float(self.sylhet.rating), 4.0)

    def test_wishlist_add_list_remove(self):
        self.assertEqual(self.client.get('/api/wishlist/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.post('/api/wishlist/', {'hotelId': self.dhaka.pk}).status_code, 201)
        self.assertEqual(self.client.post('/api/wishlist/', {'hotelId': self.dhaka.pk}).status_code, 200)
        self.assertEqual(self.client.post('/api/wishlist/', {'hotelId': 'abc'}).status_code, 400)
        self.assertEqual([h['name'] for h in self.client.get('/api/wishlist/').data], ['City Hotel'])

        self.assertEqual(self.client.delete(f'/api/wishlist/{self.dhaka.pk}/').status_code, 204)
        self.assertEqual(self.client.get('/api/wishlist/').data, [])


class ReviewRulesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta

        from django.utils import timezone

        from bookings.models import Booking

        cls.hotel = make_hotel('Tea Resort', 'Sylhet', 6400)
        cls.guest = User.objects.create_user(email='guest@example.com', password='S3cure-pass-77', first_name='Guest')
        cls.stranger = User.objects.create_user(email='stranger@example.com', password='S3cure-pass-77')
        start = timezone.localdate() - timedelta(days=10)
        Booking.objects.create(
            user=cls.guest, hotel=cls.hotel, room=cls.hotel.rooms.first(), check_in=start,
            check_out=start + timedelta(days=2), guest_name='Guest', guest_email='guest@example.com',
            guest_phone='01712345678', room_total=12800, tax=0, total_price=12800,
            payment_method=Booking.PaymentMethod.CARD, status=Booking.Status.COMPLETED,
        )

    def test_verified_badge_only_for_real_stays_and_one_review_each(self):
        url = f'/api/hotels/{self.hotel.pk}/reviews/'
        payload = {'rating': 5, 'travelerType': 'Couple', 'title': 'Lovely', 'comment': 'Great tea views.'}

        self.client.force_authenticate(self.guest)
        self.assertTrue(self.client.post(url, payload, format='json').data['verifiedStay'])
        again = self.client.post(url, payload, format='json')
        self.assertEqual(again.status_code, 400)
        self.assertIn('already reviewed', again.data['detail'])

        self.client.force_authenticate(self.stranger)
        self.assertFalse(self.client.post(url, payload, format='json').data['verifiedStay'])
