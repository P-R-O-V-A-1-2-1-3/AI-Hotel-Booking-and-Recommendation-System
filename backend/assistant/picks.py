"""
Personalised hotel picks for the "AI Picks" page.

Scores every active hotel against a preference profile learned from the user's
bookings and wishlist (cities, budget, amenities) and explains each pick in
plain language. Without a profile (signed out, or no history yet) hotels are
ranked on rating and current deals.
"""

from collections import Counter
from dataclasses import dataclass, field

from bookings.models import Booking
from hotels.models import Hotel, WishlistItem

from .tools import hotel_card

MAX_PICKS = 12
AMENITY_LABELS = {
    'pool': 'a pool', 'spa': 'spa & wellness', 'breakfast': 'breakfast included', 'beach': 'beach access',
    'view': 'scenic views', 'wi-fi': 'free Wi-Fi', 'gym': 'a gym', 'parking': 'free parking', 'balcony': 'a balcony',
}


@dataclass
class Profile:
    trips: int
    saved: int
    cities: Counter
    booked_cities: set
    budget_low: int
    budget_high: int
    amenities: list = field(default_factory=list)
    saved_ids: set = field(default_factory=set)


def _amenity_keys(amenities: list[str]) -> set[str]:
    text = ' '.join(amenities).lower()
    return {key for key in AMENITY_LABELS if key in text}


def build_profile(user) -> Profile | None:
    if user is None or not user.is_authenticated:
        return None
    booked = [
        b.hotel for b in Booking.objects.filter(user=user).exclude(status=Booking.Status.CANCELED).select_related('hotel')
    ]
    saved = [w.hotel for w in WishlistItem.objects.filter(user=user).select_related('hotel')]
    if not booked and not saved:
        return None

    weighted = [(h, 2) for h in booked] + [(h, 1) for h in saved]  # a stay says more than a heart
    cities, amenities = Counter(), Counter()
    for hotel, weight in weighted:
        cities[hotel.city] += weight
        for key in _amenity_keys(hotel.amenities):
            amenities[key] += weight
    prices = [h.price_per_night for h, _ in weighted if h.price_per_night] or [5000]

    return Profile(
        trips=len({h.pk for h in booked}),
        saved=len(saved),
        cities=cities,
        booked_cities={h.city for h in booked},
        budget_low=int(min(prices) * 0.7 // 500 * 500),
        budget_high=int(max(prices) * 1.3 // 500 * 500 + 500),
        amenities=[key for key, _ in amenities.most_common(4)],
        saved_ids={h.pk for h in saved},
    )


def score_hotel(hotel: Hotel, profile: Profile | None) -> tuple[int, list[str]]:
    score, reasons = 45.0, []

    if profile:
        if hotel.city in profile.cities:
            score += 15
            verb = "stayed" if hotel.city in profile.booked_cities else "saved hotels"
            reasons.append(f"In {hotel.city}, where you've {verb} before")
        shared = [k for k in profile.amenities if k in _amenity_keys(hotel.amenities)]
        if shared:
            score += min(15, 6 * len(shared))
            reasons.append(f"Has {' and '.join(AMENITY_LABELS[k] for k in shared[:2])}, like places you chose")
        if hotel.price_per_night is None:
            pass  # no price yet: neither a budget match nor a mismatch
        elif profile.budget_low <= hotel.price_per_night <= profile.budget_high:
            score += 10
            reasons.append(f'Within your usual ৳{profile.budget_low:,}–{profile.budget_high:,} budget')
        elif hotel.price_per_night < profile.budget_low:
            score += 6
            reasons.append('Below your usual nightly spend')
        if hotel.pk in profile.saved_ids:
            score += 4
            reasons.append('On your wishlist')

    rating = float(hotel.rating)
    if hotel.reviews_count:
        score += (rating - 4.0) * 20
    elif hotel.stars:
        score += (hotel.stars - 3) * 4  # unreviewed listing: lean on its official star rating
    if not hotel.is_bookable:
        score -= 12
        reasons.append('Not bookable on LuminaStay yet')
    if hotel.reviews_count:
        reasons.append(f'Rated {rating:.1f} by {hotel.reviews_count:,} guests')
    if hotel.original_price and hotel.original_price > hotel.price_per_night:
        off = round((1 - hotel.price_per_night / hotel.original_price) * 100)
        score += min(off, 20) / 4
        reasons.append(f'{off}% below its usual rate right now')

    return max(50, min(99, round(score))), reasons[:3]


def get_picks(user) -> dict:
    profile = build_profile(user)
    hotels = Hotel.objects.filter(is_active=True).prefetch_related('photos')
    picks = []
    for hotel in hotels:
        match, reasons = score_hotel(hotel, profile)
        picks.append({
            **hotel_card(hotel),
            'match': match,
            'city': hotel.city,
            'reviewsCount': hotel.reviews_count,
            'originalPrice': hotel.original_price,
            'reasons': reasons,
        })
    picks.sort(key=lambda p: (-p['match'], p['priceNum'] is None, p['priceNum'] or 0))

    if profile:
        summary = (
            f"Based on {profile.trips} past stay{'s' if profile.trips != 1 else ''} and "
            f"{profile.saved} saved hotel{'s' if profile.saved != 1 else ''}, ranked for you, with the reasons shown."
        )
        tags = [*list(profile.cities)[:3], *(AMENITY_LABELS[k] for k in profile.amenities[:3]),
                f'৳{profile.budget_low:,}–{profile.budget_high:,}']
    else:
        summary = 'Top-rated stays and current deals. Book or save hotels and your picks will adapt to you.'
        tags = []

    return {'personalized': profile is not None, 'summary': summary, 'tags': tags, 'picks': picks[:MAX_PICKS]}
