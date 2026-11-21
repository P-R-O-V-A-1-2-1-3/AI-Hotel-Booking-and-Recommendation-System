import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

RATING_VALIDATORS = [MinValueValidator(0), MaxValueValidator(5)]

# Served by the frontend (public/hotel-placeholder.svg) for hotels without any photo
PLACEHOLDER_IMAGE = '/hotel-placeholder.svg'


def absolute_media_url(path: str, request=None) -> str:
    """Uploaded files live on the API server; the frontend runs elsewhere, so URLs must be absolute."""
    if path.startswith('http'):
        return path
    if request is not None:
        return request.build_absolute_uri(path)
    return settings.BACKEND_PUBLIC_URL.rstrip('/') + path


class Hotel(models.Model):
    class Source(models.TextChoices):
        DEMO = 'demo', 'Demo data'
        OWNER = 'owner', 'Listed by owner'
        OSM = 'osm', 'OpenStreetMap import'

    class Approval(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hotels',
        limit_choices_to={'role': 'owner'},
    )
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100, db_index=True)
    location = models.CharField(max_length=255)
    description = models.TextField()

    rating = models.DecimalField(max_digits=2, decimal_places=1, default=0, validators=RATING_VALIDATORS)
    reviews_count = models.PositiveIntegerField(default=0)

    # "Starting from" price shown on listings (cheapest room); unknown for imported listings
    price_per_night = models.PositiveIntegerField(null=True, blank=True, help_text='BDT per night')
    original_price = models.PositiveIntegerField(null=True, blank=True, help_text='BDT, before discount')

    # External image URLs (demo data); owner uploads live in HotelPhoto
    image = models.URLField(max_length=500, blank=True)
    gallery = models.JSONField(default=list, blank=True)
    amenities = models.JSONField(default=list, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    featured = models.BooleanField(default=False)

    # Listing facts
    stars = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(max_length=300, blank=True)

    # Where the listing came from and where it is in the approval workflow
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.OWNER)
    external_id = models.CharField(max_length=60, null=True, blank=True, unique=True,
                                   help_text='e.g. "osm:node/123" for imported listings')
    approval_status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.APPROVED, db_index=True)
    review_note = models.TextField(blank=True, help_text="Admin's note to the owner, e.g. why it was rejected")
    submitted_at = models.DateTimeField(null=True, blank=True)

    # AI-generated content (static for now; will be produced by the recommendation agent)
    match_score = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    ai_reasoning = models.TextField(blank=True)
    ai_sentiment_summary = models.TextField(blank=True)

    # Category ratings (0–5)
    cleanliness_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True, validators=RATING_VALIDATORS)
    location_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True, validators=RATING_VALIDATORS)
    service_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True, validators=RATING_VALIDATORS)
    value_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True, validators=RATING_VALIDATORS)

    is_active = models.BooleanField(default=True, help_text='Inactive hotels are hidden (e.g. pending approval)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-featured', '-match_score', 'name']

    def __str__(self):
        return self.name

    @property
    def is_bookable(self) -> bool:
        """Live, approved, and has at least one priced room."""
        return self.is_active and self.approval_status == self.Approval.APPROVED and self.price_per_night is not None

    def photo_urls(self, request=None) -> list[str]:
        """Owner uploads first (absolute URLs), then any external image/gallery URLs, without duplicates."""
        urls = [absolute_media_url(p.image.url, request) for p in self.photos.all()]
        for url in [self.image, *self.gallery]:
            if url and url not in urls:
                urls.append(url)
        return urls

    def cover_image(self, request=None) -> str:
        urls = self.photo_urls(request)
        return urls[0] if urls else PLACEHOLDER_IMAGE

    @property
    def is_claimable(self) -> bool:
        """Imported listing nobody has claimed yet."""
        return self.source == self.Source.OSM and self.owner_id is None

    def sync_listing_price(self):
        """Keep the "from" price equal to the cheapest room (None when there are no rooms)."""
        cheapest = self.rooms.order_by('price_per_night').first()
        price = cheapest.price_per_night if cheapest else None
        if self.price_per_night != price:
            self.price_per_night = price
            self.save(update_fields=['price_per_night'])


def hotel_photo_path(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    return f'hotels/{instance.hotel_id}/{uuid.uuid4().hex}.{ext}'


class HotelPhoto(models.Model):
    """Photo uploaded by the hotel owner. The first by `order` is the cover image."""

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=hotel_photo_path)
    caption = models.CharField(max_length=120, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'Photo of {self.hotel.name}'


class HotelClaim(models.Model):
    """An owner asking to manage an imported (unclaimed) listing."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='claims')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hotel_claims')
    message = models.TextField(blank=True, help_text='How the owner can prove they run this hotel')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['hotel', 'user'], name='one_claim_per_user_per_hotel'),
        ]

    def __str__(self):
        return f'{self.user} claims {self.hotel}'


class Room(models.Model):
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='rooms')
    name = models.CharField(max_length=120)
    price_per_night = models.PositiveIntegerField(help_text='BDT per night')
    original_price = models.PositiveIntegerField(null=True, blank=True)
    capacity = models.PositiveSmallIntegerField(default=2)
    size_sqm = models.PositiveSmallIntegerField(null=True, blank=True)
    bed_type = models.CharField(max_length=60, blank=True)
    breakfast_included = models.BooleanField(default=False)
    total_units = models.PositiveSmallIntegerField(default=1, help_text='How many rooms of this type exist')

    class Meta:
        ordering = ['price_per_night']

    def __str__(self):
        return f'{self.hotel.name} — {self.name}'


class Review(models.Model):
    class TravelerType(models.TextChoices):
        COUPLE = 'Couple'
        SOLO = 'Solo'
        FAMILY = 'Family'
        BUSINESS = 'Business'

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    author_name = models.CharField(max_length=120)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    traveler_type = models.CharField(max_length=10, choices=TravelerType.choices)
    title = models.CharField(max_length=200)
    comment = models.TextField()
    photos = models.JSONField(default=list, blank=True)
    helpful_count = models.PositiveIntegerField(default=0)
    is_flagged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # One review per account per hotel (imported/anonymous reviews have no user)
            models.UniqueConstraint(fields=['hotel', 'user'], condition=models.Q(user__isnull=False),
                                    name='one_review_per_user_per_hotel'),
        ]

    def __str__(self):
        return f'{self.author_name} on {self.hotel.name}'


class WishlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist')
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'hotel'], name='unique_wishlist_item'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} ♥ {self.hotel}'
