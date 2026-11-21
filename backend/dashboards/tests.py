from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from hotels.models import Hotel, Review, Room, WishlistItem

User = get_user_model()


def make_booking(user, room, start_offset, nights, total, status=Booking.Status.CONFIRMED, discount=1500):
    check_in = timezone.localdate() + timedelta(days=start_offset)
    return Booking.objects.create(
        user=user, hotel=room.hotel, room=room, check_in=check_in, check_out=check_in + timedelta(days=nights),
        guest_name='Guest', guest_email=user.email, guest_phone='01712345678', room_total=total, tax=0,
        discount=discount, total_price=total, payment_method=Booking.PaymentMethod.CARD, status=status,
    )


class DashboardTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.traveler = User.objects.create_user(email='t@example.com', password='S3cure-pass-77', first_name='Tia')
        cls.owner = User.objects.create_user(email='o@example.com', password='S3cure-pass-77', role='owner')
        cls.other_owner = User.objects.create_user(email='o2@example.com', password='S3cure-pass-77', role='owner')
        cls.admin = User.objects.create_user(email='a@example.com', password='S3cure-pass-77', role='admin')

        cls.hotel = Hotel.objects.create(
            name='Sea Pearl', city="Cox's Bazar", location='Kolatoli', description='Beach', owner=cls.owner,
            price_per_night=7000, image='https://example.com/a.jpg', latitude=21.4, longitude=91.9, rating=4.8,
        )
        cls.room = Room.objects.create(hotel=cls.hotel, name='Deluxe', price_per_night=7000, total_units=2)
        cls.pending = Hotel.objects.create(
            name='Hillview', city='Chattogram', location='Khulshi', description='New', price_per_night=5000,
            image='https://example.com/b.jpg', latitude=22.3, longitude=91.8, is_active=False,
            approval_status=Hotel.Approval.PENDING,
        )
        cls.flagged = Review.objects.create(hotel=cls.hotel, author_name='bot', rating=5, traveler_type='Solo',
                                            title='Spam', comment='free stays', is_flagged=True)

        make_booking(cls.traveler, cls.room, -5, 2, 10000)                    # in window, completed stay
        make_booking(cls.traveler, cls.room, 10, 3, 20000)                    # upcoming
        make_booking(cls.traveler, cls.room, -3, 1, 99999, status=Booking.Status.CANCELED)
        WishlistItem.objects.create(user=cls.traveler, hotel=cls.hotel)

    def test_role_permissions(self):
        self.assertEqual(self.client.get('/api/dashboard/me/').status_code, 401)
        self.client.force_authenticate(self.traveler)
        self.assertEqual(self.client.get('/api/owner/overview/').status_code, 403)
        self.assertEqual(self.client.get('/api/admin/overview/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/admin/hotels/{self.pending.pk}/decision/').status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get('/api/admin/overview/').status_code, 403)

    def test_traveler_dashboard(self):
        self.client.force_authenticate(self.traveler)
        data = self.client.get('/api/dashboard/me/').data
        self.assertEqual(data['stats'], {'trips': 2, 'savedWithDeals': 3000, 'wishlisted': 1, 'reviewsWritten': 0})
        self.assertEqual(data['upcoming']['totalPrice'], 20000)
        self.assertEqual(len(data['recentBookings']), 3)

    def test_owner_overview(self):
        self.client.force_authenticate(self.owner)
        data = self.client.get('/api/owner/overview/?days=30').data
        self.assertEqual(data['hotel']['name'], 'Sea Pearl')
        # Only the stay that checked in inside the window counts; canceled bookings never do
        self.assertEqual(data['stats']['revenue'], 10000)
        # 2 room-nights out of 2 units × 30 days
        self.assertEqual(data['stats']['occupancyRate'], round(100 * 2 / 60))
        self.assertEqual(len(data['revenueTrend']), 30)
        self.assertEqual(data['occupancyByRoom'][0]['nights'], 2)

        self.client.force_authenticate(self.other_owner)
        self.assertEqual(self.client.get('/api/owner/overview/').data, {'hotels': [], 'hotel': None})

    def test_owner_updates_room_rates(self):
        url = f'/api/owner/rooms/{self.room.pk}/'
        self.client.force_authenticate(self.other_owner)
        self.assertEqual(self.client.patch(url, {'pricePerNight': 1000}, format='json').status_code, 404)

        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(url, {'pricePerNight': 'cheap'}, format='json').status_code, 400)
        res = self.client.patch(url, {'pricePerNight': 6500, 'totalUnits': 4}, format='json')
        self.assertEqual(res.status_code, 200)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.price_per_night, 6500)  # listing price follows the cheapest room

    def test_admin_moderation(self):
        self.client.force_authenticate(self.admin)
        data = self.client.get('/api/admin/overview/').data
        self.assertEqual(data['stats']['hotels'], 1)
        self.assertEqual([h['name'] for h in data['pendingHotels']], ['Hillview'])
        self.assertEqual(data['bookingsByCity'], [{'city': "Cox's Bazar", 'count': 2}])

        self.client.post(f'/api/admin/hotels/{self.pending.pk}/decision/', {'decision': 'approve'}, format='json')
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_active)

        self.client.post(f'/api/admin/reviews/{self.flagged.pk}/')
        self.flagged.refresh_from_db()
        self.assertFalse(self.flagged.is_flagged)
        self.assertEqual(self.client.delete(f'/api/admin/reviews/{self.flagged.pk}/').status_code, 204)

        url = f'/api/admin/users/{self.traveler.pk}/status/'
        self.assertEqual(self.client.post(url, {'active': 'no'}, format='json').status_code, 400)
        self.client.post(url, {'active': False}, format='json')
        self.traveler.refresh_from_db()
        self.assertFalse(self.traveler.is_active)
        self.assertEqual(
            self.client.post(f'/api/admin/users/{self.admin.pk}/status/', {'active': False}, format='json').status_code,
            400,
        )
