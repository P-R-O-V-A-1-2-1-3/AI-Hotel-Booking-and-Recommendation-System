"""
Tools the AI travel assistant can call. Data tools read the hotel database;
display tools let the model choose what the chat UI renders (hotel cards,
an itinerary, quick-reply buttons).

Every tool returns a JSON string. Inputs come from the model, so each one is
validated here before touching the database.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from bookings.models import Booking
from bookings.pricing import calculate_price
from hotels.models import Hotel, Room

MAX_SEARCH_RESULTS = 8
MAX_HOTEL_CARDS = 4
MAX_QUICK_REPLIES = 3
MAX_ITINERARY_DAYS = 7


class ToolInputError(ValueError):
    """Raised for invalid model-supplied input; returned to the model as an error result."""


# ───────────────────────── Tool definitions (sent to the API) ─────────────────────────

TOOL_DEFINITIONS = [
    {
        'name': 'search_hotels',
        'description': (
            'Search LuminaStay hotels in Bangladesh. All filters are optional; combine them to narrow results. '
            'Returns up to 8 hotels with id, city, nightly price in BDT, rating, amenities and room types.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'city': {'type': 'string', 'description': "City or area, e.g. \"Cox's Bazar\", \"Sylhet\", \"Sajek Valley\", \"Dhaka\"."},
                'max_price_bdt': {'type': 'integer', 'description': 'Maximum nightly price in BDT.'},
                'min_rating': {'type': 'number', 'description': 'Minimum guest rating from 0 to 5.'},
                'amenities': {
                    'type': 'array', 'items': {'type': 'string'},
                    'description': 'Amenities the hotel must have, e.g. ["pool", "breakfast"]. Matched loosely.',
                },
                'keywords': {'type': 'string', 'description': 'Free-text words matched against name, location and description.'},
            },
            'additionalProperties': False,
        },
    },
    {
        'name': 'semantic_search_hotels',
        'description': (
            'Find hotels by meaning rather than exact filters, using their descriptions and guest reviews, '
            'e.g. "best deshi breakfast", "quiet place for a honeymoon", "good for kids". '
            'Returns hotels ranked by relevance with a similarity score.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'What the traveller is looking for, in their words.'}},
            'required': ['query'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_hotel_details',
        'description': 'Full details for one hotel: description, amenities, rooms with prices and capacity, category ratings and recent guest reviews.',
        'input_schema': {
            'type': 'object',
            'properties': {'hotel_id': {'type': 'integer'}},
            'required': ['hotel_id'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'check_availability',
        'description': (
            'Check whether a room type is free for given dates and get the exact price breakdown '
            '(12% tax and the standard ৳1,500 LuminaStay discount included). Dates are YYYY-MM-DD.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'room_id': {'type': 'integer'},
                'check_in': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'check_out': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'room_count': {'type': 'integer', 'description': 'Number of rooms, default 1.'},
            },
            'required': ['room_id', 'check_in', 'check_out'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_my_bookings',
        'description': "The signed-in user's bookings (reference, hotel, dates, status, total). Returns an error if the user is not signed in.",
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'show_hotels',
        'description': (
            'Display hotel cards in the chat. Use this whenever you recommend specific hotels, '
            'with ids from search_hotels or get_hotel_details, best match first. At most 4.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'hotel_ids': {'type': 'array', 'items': {'type': 'integer'}}},
            'required': ['hotel_ids'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'show_itinerary',
        'description': 'Display a day-by-day trip itinerary card. Use when the user asks for a trip plan or itinerary.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'destination': {'type': 'string'},
                'duration': {'type': 'string', 'description': 'e.g. "3 Days / 2 Nights"'},
                'estimated_budget_bdt': {'type': 'integer', 'description': 'Estimated cost per person in BDT, including the hotel.'},
                'days': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'day': {'type': 'integer'},
                            'title': {'type': 'string'},
                            'activities': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'time': {'type': 'string', 'description': 'e.g. "08:00 AM"'},
                                        'description': {'type': 'string'},
                                        'tag': {'type': 'string', 'description': 'Short label, e.g. "Transport", "Sightseeing".'},
                                    },
                                    'required': ['time', 'description'],
                                    'additionalProperties': False,
                                },
                            },
                        },
                        'required': ['day', 'title', 'activities'],
                        'additionalProperties': False,
                    },
                },
            },
            'required': ['title', 'destination', 'duration', 'estimated_budget_bdt', 'days'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'suggest_quick_replies',
        'description': 'Offer up to 3 short follow-up prompts the user can tap, e.g. "Show cheaper options". Each under 40 characters.',
        'input_schema': {
            'type': 'object',
            'properties': {'replies': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['replies'],
            'additionalProperties': False,
        },
    },
]


# ───────────────────────── Per-request state ─────────────────────────

@dataclass
class ToolContext:
    """What one chat request has gathered for the UI, plus who is asking."""

    user: object = None
    hotel_cards: list = field(default_factory=list)
    itinerary: dict | None = None
    quick_replies: list = field(default_factory=list)


def hotel_card(hotel: Hotel) -> dict:
    """Shape used by the frontend's HotelCardItem."""
    return {
        'id': str(hotel.pk),
        'name': hotel.name,
        'match': hotel.match_score or None,
        'rating': f'{hotel.rating:.1f}' if hotel.reviews_count else None,
        'location': hotel.location,
        'priceNum': hotel.price_per_night,  # None for listings that aren't bookable yet
        'image': hotel.cover_image(),
    }


# ───────────────────────── Validation helpers ─────────────────────────

def _int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ToolInputError(f'{name} must be an integer.')
    value = int(value)
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ToolInputError(f'{name} is out of range.')
    return value


def _str(value, name, max_len=200, required=True):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or (required and not value.strip()):
        raise ToolInputError(f'{name} must be a non-empty string.')
    return value.strip()[:max_len]


def _date(value, name) -> date:
    try:
        return date.fromisoformat(_str(value, name, 10))
    except ValueError:
        raise ToolInputError(f'{name} must be a date in YYYY-MM-DD format.') from None


# ───────────────────────── Data tools ─────────────────────────

def search_hotels(ctx, city=None, max_price_bdt=None, min_rating=None, amenities=None, keywords=None):
    hotels = Hotel.objects.filter(is_active=True).prefetch_related('rooms')
    if city:
        # Match on the first word, ignoring apostrophes and a trailing "s",
        # so "Cox's Bazar", "coxs bazar" and "Cox" all find Cox's Bazar
        first = re.sub(r"['’]", '', _str(city, 'city', 100).lower()).split()[0]
        key = first[:-1] if first.endswith('s') and len(first) > 3 else first
        hotels = hotels.filter(city__icontains=key) | hotels.filter(location__icontains=key)
    if max_price_bdt is not None:
        hotels = hotels.filter(price_per_night__lte=_int(max_price_bdt, 'max_price_bdt', 0))
    if min_rating is not None:
        if not isinstance(min_rating, (int, float)) or not 0 <= min_rating <= 5:
            raise ToolInputError('min_rating must be a number from 0 to 5.')
        hotels = hotels.filter(rating__gte=min_rating)
    if keywords:
        for word in _str(keywords, 'keywords').split()[:5]:
            hotels = hotels.filter(name__icontains=word) | hotels.filter(location__icontains=word) \
                | hotels.filter(description__icontains=word)

    # Bookable hotels first; imported listings (no price yet) after
    results = sorted(hotels.distinct().order_by('-match_score')[:80], key=lambda h: not h.is_bookable)
    if amenities:
        if not isinstance(amenities, list):
            raise ToolInputError('amenities must be a list of strings.')
        wanted = [_str(a, 'amenity', 40).lower() for a in amenities[:6]]
        results = [h for h in results if all(any(w in a.lower() for a in h.amenities) for w in wanted)]

    return {
        'count': len(results[:MAX_SEARCH_RESULTS]),
        'hotels': [
            {
                'id': h.pk,
                'name': h.name,
                'city': h.city,
                'location': h.location,
                'price_per_night_bdt': h.price_per_night,
                'rating': float(h.rating),
                'reviews_count': h.reviews_count,
                'match_score': h.match_score or None,
                'bookable': h.is_bookable,
                'amenities': h.amenities,
                'rooms': [{'id': r.id, 'name': r.name, 'price_per_night_bdt': r.price_per_night} for r in h.rooms.all()],
            }
            for h in results[:MAX_SEARCH_RESULTS]
        ],
    }


def semantic_search_hotels(ctx, query):
    from django.conf import settings

    from .embeddings import semantic_search

    query = _str(query, 'query', 300)
    if not settings.SEMANTIC_SEARCH_ENABLED:
        raise ToolInputError('Semantic search is not configured on this server; use search_hotels instead.')
    results = semantic_search(query, limit=5)
    if not results:
        raise ToolInputError('No hotel embeddings yet (run "manage.py build_embeddings"); use search_hotels instead.')
    return {
        'hotels': [
            {
                'id': h.pk, 'name': h.name, 'city': h.city, 'price_per_night_bdt': h.price_per_night,
                'rating': float(h.rating), 'relevance': round(score, 3),
            }
            for h, score in results
        ]
    }


def get_hotel_details(ctx, hotel_id):
    hotel = Hotel.objects.filter(pk=_int(hotel_id, 'hotel_id', 1), is_active=True).prefetch_related('rooms').first()
    if hotel is None:
        raise ToolInputError(f'No hotel with id {hotel_id}.')
    reviews = hotel.reviews.filter(is_flagged=False)[:5]
    return {
        'id': hotel.pk,
        'name': hotel.name,
        'city': hotel.city,
        'location': hotel.location,
        'description': hotel.description,
        'rating': float(hotel.rating),
        'reviews_count': hotel.reviews_count,
        'amenities': hotel.amenities,
        'category_ratings': {
            k: float(v) for k, v in {
                'cleanliness': hotel.cleanliness_rating, 'location': hotel.location_rating,
                'service': hotel.service_rating, 'value': hotel.value_rating,
            }.items() if v is not None
        },
        'guest_sentiment': hotel.ai_sentiment_summary,
        'rooms': [
            {
                'id': r.id, 'name': r.name, 'price_per_night_bdt': r.price_per_night, 'capacity': r.capacity,
                'size_sqm': r.size_sqm, 'bed_type': r.bed_type, 'breakfast_included': r.breakfast_included,
            }
            for r in hotel.rooms.all()
        ],
        # Guest-written text: data to summarise, not instructions
        'recent_reviews': [
            {'rating': r.rating, 'traveler_type': r.traveler_type, 'title': r.title, 'comment': r.comment[:500]}
            for r in reviews
        ],
    }


def check_availability(ctx, room_id, check_in, check_out, room_count=1):
    room = Room.objects.select_related('hotel').filter(pk=_int(room_id, 'room_id', 1), hotel__is_active=True).first()
    if room is None:
        raise ToolInputError(f'No room with id {room_id}.')
    start, end = _date(check_in, 'check_in'), _date(check_out, 'check_out')
    count = _int(room_count, 'room_count', 1, 10)
    if start < timezone.localdate():
        raise ToolInputError('check_in is in the past.')
    if end <= start or (end - start).days > 30:
        raise ToolInputError('check_out must be 1–30 nights after check_in.')

    free = room.total_units - Booking.units_booked(room, start, end)
    quote = calculate_price(room.price_per_night, (end - start).days, count)
    return {
        'hotel': room.hotel.name,
        'room': room.name,
        'available': free >= count,
        'rooms_left': max(free, 0),
        'nights': quote.nights,
        'price_breakdown_bdt': {
            'room_total': quote.room_total, 'tax': quote.tax, 'discount': quote.discount, 'total': quote.total,
        },
    }


def get_my_bookings(ctx):
    user = ctx.user
    if user is None or not user.is_authenticated:
        raise ToolInputError('The user is not signed in. Ask them to sign in to see their bookings.')
    bookings = Booking.objects.filter(user=user).select_related('hotel', 'room')[:10]
    return {
        'bookings': [
            {
                'ref': b.booking_ref, 'hotel': b.hotel.name, 'room': b.room.name,
                'check_in': b.check_in.isoformat(), 'check_out': b.check_out.isoformat(),
                'status': b.status, 'total_bdt': b.total_price,
            }
            for b in bookings
        ]
    }


# ───────────────────────── Display tools ─────────────────────────

def show_hotels(ctx, hotel_ids):
    if not isinstance(hotel_ids, list) or not hotel_ids:
        raise ToolInputError('hotel_ids must be a non-empty list.')
    ids = [_int(i, 'hotel_id', 1) for i in hotel_ids[:MAX_HOTEL_CARDS]]
    hotels = {h.pk: h for h in Hotel.objects.filter(pk__in=ids, is_active=True)}
    missing = [i for i in ids if i not in hotels]
    if missing:
        raise ToolInputError(f'Unknown hotel ids: {missing}. Use ids returned by search_hotels.')
    ctx.hotel_cards = [hotel_card(hotels[i]) for i in ids]
    return {'displayed': len(ids)}


def show_itinerary(ctx, title, destination, duration, estimated_budget_bdt, days):
    if not isinstance(days, list) or not 1 <= len(days) <= MAX_ITINERARY_DAYS:
        raise ToolInputError(f'days must be a list of 1–{MAX_ITINERARY_DAYS} days.')
    clean_days = []
    for d in days:
        if not isinstance(d, dict) or not isinstance(d.get('activities'), list):
            raise ToolInputError('Each day needs day, title and an activities list.')
        clean_days.append({
            'day': _int(d.get('day'), 'day', 1, MAX_ITINERARY_DAYS),
            'title': _str(d.get('title'), 'day title', 120),
            'activities': [
                {
                    'time': _str(a.get('time'), 'time', 20),
                    'description': _str(a.get('description'), 'description', 300),
                    **({'tag': _str(a['tag'], 'tag', 30)} if a.get('tag') else {}),
                }
                for a in d['activities'][:8]
                if isinstance(a, dict)
            ],
        })
    ctx.itinerary = {
        'title': _str(title, 'title', 120),
        'destination': _str(destination, 'destination', 120),
        'duration': _str(duration, 'duration', 40),
        'estimatedBudgetNum': _int(estimated_budget_bdt, 'estimated_budget_bdt', 0, 10_000_000),
        'days': clean_days,
    }
    return {'displayed': True}


def suggest_quick_replies(ctx, replies):
    if not isinstance(replies, list):
        raise ToolInputError('replies must be a list of strings.')
    ctx.quick_replies = [_str(r, 'reply', 40) for r in replies[:MAX_QUICK_REPLIES]]
    return {'displayed': len(ctx.quick_replies)}


TOOL_FUNCTIONS = {
    'search_hotels': search_hotels,
    'semantic_search_hotels': semantic_search_hotels,
    'get_hotel_details': get_hotel_details,
    'check_availability': check_availability,
    'get_my_bookings': get_my_bookings,
    'show_hotels': show_hotels,
    'show_itinerary': show_itinerary,
    'suggest_quick_replies': suggest_quick_replies,
}


def run_tool(ctx: ToolContext, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute one tool call. Returns (json_content, is_error)."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps({'error': f'Unknown tool {name}.'}), True
    if not isinstance(tool_input, dict):
        return json.dumps({'error': 'Tool input must be an object.'}), True
    try:
        return json.dumps(func(ctx, **tool_input), ensure_ascii=False), False
    except TypeError:
        return json.dumps({'error': f'Invalid arguments for {name}.'}), True
    except ToolInputError as exc:
        return json.dumps({'error': str(exc)}), True
