"""
Load the demo hotels, rooms and reviews the frontend currently mocks in
frontend/src/services/api.ts, plus a demo traveler account.

    python manage.py seed_demo

Safe to re-run: records are matched by name/email and updated in place.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking
from bookings.pricing import calculate_price
from hotels.models import Hotel, Review, Room

PEXELS = 'https://images.pexels.com/photos/{id}/pexels-photo-{id}.jpeg?auto=compress&cs=tinysrgb&w={w}'


def img(photo_id: int, w: int = 1000) -> str:
    return PEXELS.format(id=photo_id, w=w)


HOTELS = [
    {
        'name': 'Sea Pearl Beach Resort & Spa',
        'location': "Kolatoli Beach, Cox's Bazar",
        'city': "Cox's Bazar",
        'rating': 4.8, 'reviews_count': 1204,
        'price_per_night': 7650, 'original_price': 9200, 'match_score': 96,
        'image': img(258154),
        'gallery': [img(258154), img(164595, 800), img(271618, 800), img(262047, 800), img(261102, 800)],
        'description': 'Set directly on Kolatoli Beach, Sea Pearl Beach Resort & Spa offers panoramic ocean views, '
                       'a full-service spa, and multiple dining options. Rooms feature private balconies, premium '
                       'bedding, and modern amenities.',
        'amenities': ['Free Wi-Fi', 'Swimming pool', 'Spa & wellness', 'Breakfast included', 'Free parking',
                      'Fitness center', 'Beachfront'],
        'latitude': 21.4172, 'longitude': 91.9804, 'featured': True,
        'ai_reasoning': 'Matches your preference for oceanview rooms and spa access. Guests with similar taste '
                        'rated the breakfast and beach proximity highly.',
        'ratings': (4.9, 5.0, 4.8, 4.6),
        'ai_sentiment_summary': '96% of recent guests praised the oceanview breakfast buffet and private beach '
                                'access. Highly recommended for couples and families.',
        'rooms': [
            {'name': 'Deluxe Sea View Room', 'price_per_night': 7650, 'original_price': 9200, 'capacity': 2,
             'size_sqm': 32, 'bed_type': '1 King Bed', 'breakfast_included': True, 'total_units': 5},
            {'name': 'Ocean Front Suite', 'price_per_night': 12500, 'original_price': 14000, 'capacity': 3,
             'size_sqm': 48, 'bed_type': '1 King Bed + Sofa Bed', 'breakfast_included': True, 'total_units': 2},
        ],
    },
    {
        'name': 'Grand Sylhet Hotel & Resort',
        'location': 'Khadimnagar, Sylhet',
        'city': 'Sylhet',
        'rating': 4.7, 'reviews_count': 840,
        'price_per_night': 6400, 'original_price': 7800, 'match_score': 92,
        'image': img(189296),
        'gallery': [img(189296), img(261102, 800)],
        'description': 'Surrounded by lush tea estates in Sylhet, Grand Sylhet Resort offers tranquility, infinity '
                       'pools, and authentic Bangladeshi dining.',
        'amenities': ['Tea garden view', 'Swimming pool', 'Free Wi-Fi', 'Restaurant', 'Airport shuttle',
                      'Breakfast included'],
        'latitude': 24.8949, 'longitude': 91.8687, 'featured': True,
        'ai_reasoning': "Ideal choice for nature lovers seeking quiet luxury near Sylhet's iconic tea gardens.",
        'ratings': (4.8, 4.9, 4.7, 4.5),
        'ai_sentiment_summary': '92% of nature travelers loved the morning tea estate views and infinity pool '
                                'tranquility.',
        'rooms': [
            {'name': 'Tea Garden View Suite', 'price_per_night': 6400, 'original_price': 7800, 'capacity': 2,
             'size_sqm': 36, 'bed_type': '1 Queen Bed', 'breakfast_included': True, 'total_units': 4},
        ],
    },
    {
        'name': 'Sajek Cloud Retreat Resort',
        'location': 'Ruilui Para, Sajek Valley',
        'city': 'Sajek Valley',
        'rating': 4.9, 'reviews_count': 512,
        'price_per_night': 5200, 'original_price': 6200, 'match_score': 95,
        'image': img(1666021),
        'gallery': [img(1666021)],
        'description': 'Perched above the clouds in Sajek, featuring panoramic balcony views, campfire dining, and '
                       'cozy wooden cottages.',
        'amenities': ['Mountain view', 'Campfire area', 'Breakfast included', 'Free Wi-Fi', 'Balcony'],
        'latitude': 23.3820, 'longitude': 92.2938, 'featured': True,
        'ai_reasoning': 'Highest rated hill station eco-resort with 100% cloud sea visibility rating in morning hours.',
        'ratings': (4.9, 5.0, 4.8, 4.8),
        'ai_sentiment_summary': '100% cloud sea view satisfaction score. Guests loved evening campfires and wooden '
                                'balcony breakfasts.',
        'rooms': [
            {'name': 'Cloud View Wooden Cottage', 'price_per_night': 5200, 'original_price': 6200, 'capacity': 2,
             'size_sqm': 28, 'bed_type': '1 Double Bed', 'breakfast_included': True, 'total_units': 6},
        ],
    },
    {
        'name': 'InterContinental Dhaka',
        'location': 'Minto Road, Dhaka',
        'city': 'Dhaka',
        'rating': 4.8, 'reviews_count': 2150,
        'price_per_night': 14500, 'original_price': 16800, 'match_score': 89,
        'image': img(261102),
        'gallery': [img(261102)],
        'description': 'The luxury 5-star landmark in the heart of Dhaka. State-of-the-art business facilities, '
                       'fine dining, and rooftop temperature-controlled pool.',
        'amenities': ['5-Star Luxury', 'Rooftop Pool', 'Spa & Sauna', 'Fine Dining', 'Valet Parking', '24h Gym'],
        'latitude': 23.7389, 'longitude': 90.3958, 'featured': False,
        'ai_reasoning': 'Top business travel match in Dhaka with proximity to government quarters and diplomatic area.',
        'ratings': (5.0, 4.9, 4.9, 4.4),
        'ai_sentiment_summary': 'Top rated 5-star choice for corporate business trips, rooftop pool ambiance, and '
                                'high-speed fiber internet.',
        'rooms': [
            {'name': 'Club King Room', 'price_per_night': 14500, 'original_price': 16800, 'capacity': 2,
             'size_sqm': 40, 'bed_type': '1 King Bed', 'breakfast_included': False, 'total_units': 8},
        ],
    },
]

REVIEWS = [
    {
        'hotel': 'Sea Pearl Beach Resort & Spa',
        'author_name': 'Tanvir Hossain', 'rating': 5, 'traveler_type': 'Couple',
        'title': 'Unforgettable Sunset Views & Flawless Beach Proximity!',
        'comment': "LuminaStay AI recommended this resort based on our wish for oceanview balconies, and it exceeded "
                   "every expectation. Waking up to the sound of Cox's Bazar waves and enjoying the hot buffet "
                   "breakfast was pure bliss!",
        'photos': [img(258154, 400), img(164595, 400)],
        'helpful_count': 24,
    },
    {
        'hotel': 'Sea Pearl Beach Resort & Spa',
        'author_name': 'Farhana Ahmed', 'rating': 5, 'traveler_type': 'Family',
        'title': 'Super Clean Rooms & Kids Loved the Swimming Pool',
        'comment': 'The staff went above and beyond for our family stay. Fast check-in with the LuminaStay digital '
                   'voucher QR code at the desk!',
        'photos': [],
        'helpful_count': 18,
    },
]

DEMO_USER = {
    'email': 'nadia@example.com',
    'password': 'password123',  # matches the frontend's "fill demo account" button; dev only
    'first_name': 'Nadia',
    'last_name': 'Rahman',
    'phone': '+880 1712-345678',
}


DEMO_OWNER = {
    'email': 'rehana@example.com', 'password': 'password123', 'first_name': 'Rehana', 'last_name': 'Khan',
    'phone': '+880 1811-223344', 'role': 'owner',
}
DEMO_ADMIN = {
    'email': 'admin@example.com', 'password': 'password123', 'first_name': 'Arif', 'last_name': 'Chowdhury',
    'role': 'admin', 'is_staff': True,
}
SECOND_TRAVELER = {
    'email': 'tanvir@example.com', 'password': 'password123', 'first_name': 'Tanvir', 'last_name': 'Ahmed',
    'phone': '+880 1911-556677',
}
OWNER_HOTELS = ['Sea Pearl Beach Resort & Spa', 'Grand Sylhet Hotel & Resort']

PENDING_HOTEL = {
    'name': 'Hillview Residency', 'city': 'Chattogram', 'location': 'Khulshi Hills, Chattogram',
    'description': 'Boutique hilltop hotel overlooking the port city, awaiting approval.',
    'price_per_night': 5400, 'image': img(1838554), 'gallery': [img(1838554)],
    'amenities': ['Free Wi-Fi', 'Restaurant', 'City view'], 'latitude': 22.3569, 'longitude': 91.7832,
    'is_active': False, 'source': 'demo', 'approval_status': 'pending',
}
FLAGGED_REVIEW = {
    'title': 'Free stays here!!!', 'author_name': 'promo_bot', 'rating': 5, 'traveler_type': 'Solo',
    'comment': 'Click here for free stays www.suspicious-link.example', 'is_flagged': True,
}

# (traveler index, hotel, room, check-in offset from today in days, nights, add-ons)
DEMO_BOOKINGS = [
    (0, 'Sea Pearl Beach Resort & Spa', 'Deluxe Sea View Room', -26, 3, ['transfer']),
    (1, 'Sea Pearl Beach Resort & Spa', 'Ocean Front Suite', -19, 2, []),
    (1, 'Sea Pearl Beach Resort & Spa', 'Deluxe Sea View Room', -11, 4, ['spa']),
    (0, 'Grand Sylhet Hotel & Resort', 'Tea Garden View Suite', -8, 2, ['tour']),
    (1, 'Sea Pearl Beach Resort & Spa', 'Deluxe Sea View Room', -4, 3, ['transfer']),
    (0, 'Sea Pearl Beach Resort & Spa', 'Ocean Front Suite', 21, 3, ['transfer']),
]


class Command(BaseCommand):
    help = 'Seed the database with demo hotels, rooms, reviews and a demo traveler account.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()

        user, created = User.objects.get_or_create(
            email=DEMO_USER['email'],
            defaults={k: v for k, v in DEMO_USER.items() if k not in ('email', 'password')},
        )
        if created:
            user.set_password(DEMO_USER['password'])
            user.save()

        for data in HOTELS:
            data = dict(data)
            rooms = data.pop('rooms')
            cleanliness, location, service, value = data.pop('ratings')
            hotel, _ = Hotel.objects.update_or_create(
                name=data.pop('name'),
                defaults={
                    **data,
                    'source': Hotel.Source.DEMO,
                    'cleanliness_rating': cleanliness,
                    'location_rating': location,
                    'service_rating': service,
                    'value_rating': value,
                },
            )
            for room in rooms:
                room = dict(room)
                Room.objects.update_or_create(hotel=hotel, name=room.pop('name'), defaults=room)

        for data in REVIEWS:
            data = dict(data)
            hotel = Hotel.objects.get(name=data.pop('hotel'))
            Review.objects.update_or_create(hotel=hotel, title=data.pop('title'), defaults=data)

        owner = self._account(User, DEMO_OWNER)
        admin = self._account(User, DEMO_ADMIN)
        Hotel.objects.filter(name__in=OWNER_HOTELS).update(owner=owner)

        # Moderation queue for the admin panel
        Hotel.objects.update_or_create(name=PENDING_HOTEL['name'], defaults=PENDING_HOTEL)
        Review.objects.update_or_create(
            hotel=Hotel.objects.get(name='Grand Sylhet Hotel & Resort'), title=FLAGGED_REVIEW['title'],
            defaults={k: v for k, v in FLAGGED_REVIEW.items() if k != 'title'},
        )

        travelers = [user, self._account(User, SECOND_TRAVELER)]
        created = self._seed_bookings(travelers)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Hotel.objects.count()} hotels, {Room.objects.count()} rooms, '
            f'{Review.objects.count()} reviews, {created} new demo bookings.\n'
            f'Demo logins (password "{DEMO_USER["password"]}"): traveler {DEMO_USER["email"]}, '
            f'owner {owner.email}, admin {admin.email}'
        ))

    def _account(self, User, data):
        account, created = User.objects.get_or_create(
            email=data['email'],
            defaults={k: v for k, v in data.items() if k not in ('email', 'password')},
        )
        if created:
            account.set_password(data['password'])
            account.save()
        return account

    def _seed_bookings(self, travelers) -> int:
        """Past and upcoming stays (relative to today) so dashboards have data. Skips ones already seeded."""
        today = timezone.localdate()
        created = 0
        for traveler_index, hotel_name, room_name, start_offset, nights, addons in DEMO_BOOKINGS:
            traveler = travelers[traveler_index]
            room = Room.objects.select_related('hotel').get(hotel__name=hotel_name, name=room_name)
            check_in = today + timedelta(days=start_offset)
            if Booking.objects.filter(user=traveler, room=room, check_in=check_in).exists():
                continue
            quote = calculate_price(room.price_per_night, nights, addons=addons)
            Booking.objects.create(
                user=traveler, hotel=room.hotel, room=room,
                check_in=check_in, check_out=check_in + timedelta(days=nights), adults=2,
                guest_name=traveler.get_full_name(), guest_email=traveler.email, guest_phone=traveler.phone,
                addons=addons, room_total=quote.room_total, tax=quote.tax, addons_total=quote.addons_total,
                discount=quote.discount, total_price=quote.total, payment_method=Booking.PaymentMethod.BKASH,
                payment_account='017******78',
                status=Booking.Status.COMPLETED if start_offset + nights <= 0 else Booking.Status.CONFIRMED,
            )
            created += 1
        return created
