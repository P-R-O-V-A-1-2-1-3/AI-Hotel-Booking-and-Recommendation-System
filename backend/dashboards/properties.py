"""
Owner self-service: list a hotel, manage its rooms and photos, submit it for
admin review, and claim an imported (OpenStreetMap) listing.

    GET/POST         /api/owner/hotels/                 my properties / create a draft
    GET/PATCH/DELETE /api/owner/hotels/{id}/            edit details (delete: drafts/rejected only)
    POST             /api/owner/hotels/{id}/submit/     send for admin review
    POST             /api/owner/hotels/{id}/photos/     upload photos (multipart "photos")
    DELETE           /api/owner/photos/{id}/
    POST             /api/owner/hotels/{id}/rooms/      add a room
    PATCH/DELETE     /api/owner/rooms/{id}/
    GET/POST         /api/owner/claims/                 my claims / claim a listing
    GET              /api/owner/claimable/?search=      imported listings nobody has claimed
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from hotels.models import Hotel, HotelClaim, HotelPhoto, Room

from .views import IsHotelOwner, is_admin

ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
# Bangladesh bounding box (with a margin) to catch swapped or mistyped coordinates
BD_LAT, BD_LNG = (20.3, 26.8), (87.9, 92.8)


# ───────────────────────── Serializers ─────────────────────────

class OwnerRoomSerializer(serializers.ModelSerializer):
    pricePerNight = serializers.IntegerField(source='price_per_night', min_value=100, max_value=1_000_000)
    originalPrice = serializers.IntegerField(source='original_price', min_value=100, max_value=1_000_000,
                                             allow_null=True, required=False)
    capacity = serializers.IntegerField(min_value=1, max_value=20, required=False)
    sizeSqm = serializers.IntegerField(source='size_sqm', min_value=5, max_value=2000, allow_null=True, required=False)
    bedType = serializers.CharField(source='bed_type', max_length=60, allow_blank=True, required=False)
    breakfastIncluded = serializers.BooleanField(source='breakfast_included', required=False)
    totalUnits = serializers.IntegerField(source='total_units', min_value=0, max_value=500, required=False)

    class Meta:
        model = Room
        fields = ['id', 'name', 'pricePerNight', 'originalPrice', 'capacity', 'sizeSqm', 'bedType',
                  'breakfastIncluded', 'totalUnits']

    def validate(self, attrs):
        price = attrs.get('price_per_night', getattr(self.instance, 'price_per_night', None))
        original = attrs.get('original_price', getattr(self.instance, 'original_price', None))
        if original is not None and price is not None and original < price:
            raise serializers.ValidationError({'originalPrice': 'The "was" price must be higher than the current price.'})
        return attrs


class OwnerHotelSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    description = serializers.CharField(max_length=3000, allow_blank=True, required=False)
    location = serializers.CharField(max_length=255, help_text='Street / area')
    amenities = serializers.ListField(child=serializers.CharField(max_length=60), max_length=40, required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, required=False)
    stars = serializers.IntegerField(min_value=1, max_value=5, allow_null=True, required=False)
    phone = serializers.CharField(max_length=40, allow_blank=True, required=False)
    website = serializers.URLField(max_length=300, allow_blank=True, required=False)
    approvalStatus = serializers.CharField(source='approval_status', read_only=True)
    reviewNote = serializers.CharField(source='review_note', read_only=True)
    isActive = serializers.BooleanField(source='is_active', read_only=True)
    pricePerNight = serializers.IntegerField(source='price_per_night', read_only=True)
    source = serializers.CharField(read_only=True)
    rooms = OwnerRoomSerializer(many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    checklist = serializers.SerializerMethodField()

    class Meta:
        model = Hotel
        fields = ['id', 'name', 'city', 'location', 'description', 'amenities', 'latitude', 'longitude', 'stars',
                  'phone', 'website', 'approvalStatus', 'reviewNote', 'isActive', 'pricePerNight', 'source',
                  'rooms', 'photos', 'checklist']

    def get_photos(self, obj):
        request = self.context.get('request')
        return [{'id': p.pk, 'url': request.build_absolute_uri(p.image.url) if request else p.image.url,
                 'caption': p.caption} for p in obj.photos.all()]

    def get_checklist(self, obj):
        return submission_checklist(obj)

    def validate_amenities(self, value):
        seen, cleaned = set(), []
        for item in value:
            item = item.strip()
            if item and item.lower() not in seen:
                seen.add(item.lower())
                cleaned.append(item)
        return cleaned

    def validate(self, attrs):
        lat = attrs.get('latitude', getattr(self.instance, 'latitude', None))
        lng = attrs.get('longitude', getattr(self.instance, 'longitude', None))
        if (lat is None) != (lng is None):
            raise serializers.ValidationError({'latitude': 'Give both latitude and longitude, or neither.'})
        if lat is not None and not (BD_LAT[0] <= lat <= BD_LAT[1] and BD_LNG[0] <= lng <= BD_LNG[1]):
            raise serializers.ValidationError({'latitude': 'These coordinates are outside Bangladesh.'})
        return attrs


def submission_checklist(hotel: Hotel) -> dict:
    """What an owner must provide before an admin can review the listing."""
    return {
        'description': len(hotel.description.strip()) >= 40,
        'rooms': hotel.rooms.exists(),
        'photos': hotel.photos.exists() or bool(hotel.image),
        'location': bool(hotel.city.strip() and hotel.location.strip()),
    }


# ───────────────────────── Helpers ─────────────────────────

def owned_hotel(request, pk) -> Hotel:
    hotels = Hotel.objects.all() if is_admin(request.user) else Hotel.objects.filter(owner=request.user)
    return get_object_or_404(hotels.prefetch_related('rooms', 'photos'), pk=pk)


def owned_room(request, pk) -> Room:
    rooms = Room.objects.select_related('hotel')
    if not is_admin(request.user):
        rooms = rooms.filter(hotel__owner=request.user)
    return get_object_or_404(rooms, pk=pk)


def hotel_response(request, hotel, status_code=status.HTTP_200_OK):
    hotel = Hotel.objects.prefetch_related('rooms', 'photos').get(pk=hotel.pk)
    return Response(OwnerHotelSerializer(hotel, context={'request': request}).data, status=status_code)


def validate_image(upload) -> str | None:
    """Returns an error message, or None if the upload is a real JPEG/PNG/WebP within the size limit."""
    if upload.size > settings.HOTEL_PHOTO_MAX_BYTES:
        return f'{upload.name}: larger than {settings.HOTEL_PHOTO_MAX_BYTES // (1024 * 1024)} MB.'
    try:
        with Image.open(upload) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        return f'{upload.name}: not a valid image.'
    finally:
        upload.seek(0)
    if fmt not in ALLOWED_IMAGE_FORMATS:
        return f'{upload.name}: use JPEG, PNG or WebP.'
    return None


# ───────────────────────── Properties ─────────────────────────

class OwnerHotelListView(APIView):
    permission_classes = [IsHotelOwner]

    def get(self, request):
        hotels = Hotel.objects.filter(owner=request.user).prefetch_related('rooms', 'photos').order_by('-created_at')
        return Response(OwnerHotelSerializer(hotels, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = OwnerHotelSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        # New listings start as private drafts until the owner submits them
        hotel = serializer.save(owner=request.user, source=Hotel.Source.OWNER, approval_status=Hotel.Approval.DRAFT,
                                is_active=False)
        return hotel_response(request, hotel, status.HTTP_201_CREATED)


class OwnerHotelDetailView(APIView):
    permission_classes = [IsHotelOwner]

    def get(self, request, pk):
        return hotel_response(request, owned_hotel(request, pk))

    def patch(self, request, pk):
        hotel = owned_hotel(request, pk)
        serializer = OwnerHotelSerializer(hotel, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return hotel_response(request, hotel)

    def delete(self, request, pk):
        hotel = owned_hotel(request, pk)
        if hotel.approval_status not in (Hotel.Approval.DRAFT, Hotel.Approval.REJECTED) or hotel.bookings.exists():
            return Response({'detail': 'Only drafts or rejected listings without bookings can be deleted.'},
                            status=status.HTTP_400_BAD_REQUEST)
        hotel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OwnerHotelSubmitView(APIView):
    permission_classes = [IsHotelOwner]

    def post(self, request, pk):
        hotel = owned_hotel(request, pk)
        if hotel.approval_status == Hotel.Approval.APPROVED:
            return Response({'detail': 'This hotel is already live.'}, status=status.HTTP_400_BAD_REQUEST)
        missing = [k for k, ok in submission_checklist(hotel).items() if not ok]
        if missing:
            return Response({'detail': 'Complete your listing before submitting.', 'missing': missing},
                            status=status.HTTP_400_BAD_REQUEST)
        hotel.approval_status = Hotel.Approval.PENDING
        hotel.submitted_at = timezone.now()
        hotel.review_note = ''
        hotel.save(update_fields=['approval_status', 'submitted_at', 'review_note'])
        return hotel_response(request, hotel)


class OwnerHotelPhotosView(APIView):
    permission_classes = [IsHotelOwner]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        hotel = owned_hotel(request, pk)
        uploads = request.FILES.getlist('photos')
        if not uploads:
            return Response({'photos': 'Choose at least one image.'}, status=status.HTTP_400_BAD_REQUEST)
        room_left = settings.HOTEL_PHOTO_MAX_COUNT - hotel.photos.count()
        if len(uploads) > room_left:
            return Response({'photos': f'You can add {max(room_left, 0)} more photo(s) '
                                       f'(limit {settings.HOTEL_PHOTO_MAX_COUNT}).'},
                            status=status.HTTP_400_BAD_REQUEST)
        errors = [e for e in (validate_image(f) for f in uploads) if e]
        if errors:
            return Response({'photos': errors}, status=status.HTTP_400_BAD_REQUEST)

        next_order = (hotel.photos.order_by('-order').values_list('order', flat=True).first() or 0) + 1
        for i, upload in enumerate(uploads):
            HotelPhoto.objects.create(hotel=hotel, image=upload, order=next_order + i)
        return hotel_response(request, hotel, status.HTTP_201_CREATED)


class OwnerPhotoView(APIView):
    permission_classes = [IsHotelOwner]

    def delete(self, request, pk):
        photos = HotelPhoto.objects.all() if is_admin(request.user) else HotelPhoto.objects.filter(hotel__owner=request.user)
        photo = get_object_or_404(photos, pk=pk)
        photo.image.delete(save=False)
        photo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ───────────────────────── Rooms ─────────────────────────

class OwnerHotelRoomsView(APIView):
    permission_classes = [IsHotelOwner]

    def post(self, request, pk):
        hotel = owned_hotel(request, pk)
        serializer = OwnerRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save(hotel=hotel)
        hotel.sync_listing_price()
        return Response(OwnerRoomSerializer(room).data, status=status.HTTP_201_CREATED)


class OwnerRoomView(APIView):
    permission_classes = [IsHotelOwner]

    def patch(self, request, pk):
        room = owned_room(request, pk)
        serializer = OwnerRoomSerializer(room, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        room.hotel.sync_listing_price()
        return Response(OwnerRoomSerializer(room).data)

    def delete(self, request, pk):
        room = owned_room(request, pk)
        if Booking.objects.filter(room=room).exists():
            return Response({'detail': 'This room has bookings. Set its room count to 0 to stop new bookings instead.'},
                            status=status.HTTP_400_BAD_REQUEST)
        hotel = room.hotel
        room.delete()
        hotel.sync_listing_price()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ───────────────────────── Claims ─────────────────────────

def claim_json(claim: HotelClaim) -> dict:
    return {
        'id': claim.pk, 'hotelId': str(claim.hotel_id), 'hotelName': claim.hotel.name, 'city': claim.hotel.city,
        'status': claim.status, 'message': claim.message, 'created': claim.created_at.date().isoformat(),
    }


class OwnerClaimsView(APIView):
    permission_classes = [IsHotelOwner]

    def get(self, request):
        claims = HotelClaim.objects.filter(user=request.user).select_related('hotel')
        return Response([claim_json(c) for c in claims])

    def post(self, request):
        hotel_id = str(request.data.get('hotelId', ''))
        if not hotel_id.isdigit():
            return Response({'hotelId': 'Choose a listing to claim.'}, status=status.HTTP_400_BAD_REQUEST)
        hotel = get_object_or_404(Hotel, pk=hotel_id)
        if not hotel.is_claimable:
            return Response({'detail': 'This listing already has an owner on LuminaStay.'},
                            status=status.HTTP_400_BAD_REQUEST)
        message = str(request.data.get('message', '')).strip()[:1000]
        try:
            with transaction.atomic():
                claim = HotelClaim.objects.create(hotel=hotel, user=request.user, message=message)
        except IntegrityError:
            return Response({'detail': "You've already claimed this listing."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(claim_json(claim), status=status.HTTP_201_CREATED)


class ClaimableHotelsView(APIView):
    permission_classes = [IsHotelOwner]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        hotels = Hotel.objects.filter(source=Hotel.Source.OSM, owner__isnull=True, is_active=True)
        if search:
            hotels = hotels.filter(Q(name__icontains=search) | Q(city__icontains=search) | Q(location__icontains=search))
        return Response([
            {'id': str(h.pk), 'name': h.name, 'city': h.city, 'location': h.location, 'stars': h.stars}
            for h in hotels.order_by('name')[:20]
        ])
