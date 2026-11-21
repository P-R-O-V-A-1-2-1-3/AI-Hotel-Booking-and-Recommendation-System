"""
Serializers use camelCase field names that match the frontend's TypeScript
types in frontend/src/services/api.ts (Hotel, Review), so the UI can switch
from mock data to the API without reshaping responses.
"""

from rest_framework import serializers

from .models import Hotel, Review, Room


class RoomSerializer(serializers.ModelSerializer):
    pricePerNight = serializers.IntegerField(source='price_per_night')
    originalPrice = serializers.IntegerField(source='original_price', allow_null=True)
    sizeSqm = serializers.IntegerField(source='size_sqm', allow_null=True)
    bedType = serializers.CharField(source='bed_type')
    breakfastIncluded = serializers.BooleanField(source='breakfast_included')

    class Meta:
        model = Room
        fields = ['id', 'name', 'pricePerNight', 'originalPrice', 'capacity', 'sizeSqm', 'bedType', 'breakfastIncluded']


class HotelSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    rating = serializers.FloatField()
    reviewsCount = serializers.IntegerField(source='reviews_count')
    # null for imported listings that have no rooms/prices yet
    pricePerNight = serializers.IntegerField(source='price_per_night', allow_null=True)
    originalPrice = serializers.IntegerField(source='original_price', allow_null=True)
    matchScore = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    gallery = serializers.SerializerMethodField()
    coordinates = serializers.SerializerMethodField()
    aiReasoning = serializers.CharField(source='ai_reasoning')
    categoryRatings = serializers.SerializerMethodField()
    aiSentimentSummary = serializers.CharField(source='ai_sentiment_summary')
    roomType = serializers.SerializerMethodField()
    isBookable = serializers.BooleanField(source='is_bookable', read_only=True)
    isClaimable = serializers.BooleanField(source='is_claimable', read_only=True)

    class Meta:
        model = Hotel
        fields = [
            'id', 'name', 'location', 'city', 'rating', 'reviewsCount', 'pricePerNight', 'originalPrice',
            'matchScore', 'image', 'gallery', 'description', 'amenities', 'coordinates', 'featured',
            'aiReasoning', 'categoryRatings', 'aiSentimentSummary', 'roomType',
            'isBookable', 'isClaimable', 'source', 'stars', 'phone', 'website',
        ]

    def get_matchScore(self, obj):
        # 0 means "never scored" (e.g. imported listings); the UI hides the badge
        return obj.match_score or None

    def get_image(self, obj):
        return obj.cover_image(self.context.get('request'))

    def get_gallery(self, obj):
        return obj.photo_urls(self.context.get('request'))

    def get_coordinates(self, obj):
        if obj.latitude is None or obj.longitude is None:
            return None
        return {'lat': float(obj.latitude), 'lng': float(obj.longitude)}

    def get_categoryRatings(self, obj):
        ratings = {
            'cleanliness': obj.cleanliness_rating,
            'location': obj.location_rating,
            'service': obj.service_rating,
            'value': obj.value_rating,
        }
        if any(v is None for v in ratings.values()):
            return None
        return {k: float(v) for k, v in ratings.items()}

    def get_roomType(self, obj):
        # Cheapest room's name — rooms are prefetched and ordered by price
        rooms = list(obj.rooms.all())
        return rooms[0].name if rooms else None


class HotelDetailSerializer(HotelSerializer):
    rooms = RoomSerializer(many=True, read_only=True)

    class Meta(HotelSerializer.Meta):
        fields = HotelSerializer.Meta.fields + ['rooms']


class ReviewSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    hotelId = serializers.CharField(source='hotel_id', read_only=True)
    author = serializers.CharField(source='author_name', read_only=True)
    authorAvatar = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    travelerType = serializers.ChoiceField(source='traveler_type', choices=Review.TravelerType.choices)
    helpfulCount = serializers.IntegerField(source='helpful_count', read_only=True)
    verifiedStay = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ['id', 'hotelId', 'author', 'authorAvatar', 'rating', 'date', 'travelerType', 'title',
                  'comment', 'photos', 'helpfulCount', 'verifiedStay']

    def get_verifiedStay(self, obj):
        """True only when the reviewer has a (non-canceled) booking at this hotel."""
        from bookings.models import Booking  # local import: bookings.models imports hotels.models

        if not obj.user_id:
            return False
        return Booking.objects.filter(user_id=obj.user_id, hotel_id=obj.hotel_id) \
            .exclude(status=Booking.Status.CANCELED).exists()

    def get_authorAvatar(self, obj):
        return obj.author_name[:1].upper()

    def get_date(self, obj):
        return obj.created_at.strftime('%B %d, %Y')

    def validate_photos(self, value):
        if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
            raise serializers.ValidationError('photos must be a list of URLs.')
        return value[:6]
