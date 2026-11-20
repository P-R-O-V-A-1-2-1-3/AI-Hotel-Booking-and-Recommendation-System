"""
Rule-based assistant used when no Anthropic API key is configured or the API is
unavailable. It pulls a city, budget and amenities out of the message and
answers from the same database tools the AI uses.
"""

import re

from hotels.models import Hotel

from .tools import ToolContext, ToolInputError, get_my_bookings, hotel_card, search_hotels

AMENITY_WORDS = {
    'pool': 'pool', 'swimming': 'pool', 'breakfast': 'breakfast', 'spa': 'spa', 'beach': 'beach',
    'wifi': 'wi-fi', 'wi-fi': 'wi-fi', 'gym': 'gym', 'fitness': 'fitness', 'parking': 'parking',
    'shuttle': 'shuttle', 'balcony': 'balcony',
}
BOOKING_WORDS = ('booking', 'bookings', 'reservation', 'voucher', 'বুকিং')
PLAN_WORDS = ('itinerary', 'plan', 'trip plan', 'day-by-day')
BANGLA_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
PRICE_RE = re.compile(
    r'(?:under|below|less than|within|max(?:imum)?|budget(?: of)?|<)\s*(?:৳|tk\.?|bdt)?\s*([\d,]{3,})'
    r'|(?:৳|tk\.?|bdt)\s*([\d,]{3,})',
    re.IGNORECASE,
)


def _detect_city(text: str) -> str | None:
    for city in Hotel.objects.filter(is_active=True).values_list('city', flat=True).distinct():
        key = city.lower().replace("'s", '').split()[0]
        if key in text.replace("'s", '').replace('’s', ''):
            return city
    return None


def _detect_max_price(text: str) -> int | None:
    match = PRICE_RE.search(text.translate(BANGLA_DIGITS))
    if not match:
        return None
    return int((match.group(1) or match.group(2)).replace(',', ''))


def run_fallback(history: list[dict], user=None) -> dict:
    prompt = next((m['text'] for m in reversed(history) if m['role'] == 'user'), '')
    text = prompt.lower()
    ctx = ToolContext(user=user)

    if any(w in text for w in BOOKING_WORDS):
        try:
            bookings = get_my_bookings(ctx)['bookings']
        except ToolInputError:
            return {'text': 'Please sign in to see your bookings.', 'quickActions': ['Show all hotels']}
        if not bookings:
            return {'text': "You don't have any bookings yet.", 'quickActions': ['Show all hotels']}
        lines = [f"• {b['ref']}: {b['hotel']}, {b['check_in']} to {b['check_out']} ({b['status']})" for b in bookings[:5]]
        return {'text': 'Here are your bookings:\n' + '\n'.join(lines), 'quickActions': ['View My Bookings']}

    city = _detect_city(text)
    max_price = _detect_max_price(text)
    amenities = sorted({v for k, v in AMENITY_WORDS.items() if re.search(rf'\b{re.escape(k)}\b', text)})

    # Relax filters until something matches: amenities first, then budget
    attempts = [(city, max_price, amenities), (city, max_price, []), (city, None, []), (None, None, [])]
    results, used = [], attempts[-1]
    for attempt in attempts:
        results = search_hotels(ctx, city=attempt[0], max_price_bdt=attempt[1], amenities=attempt[2] or None)['hotels']
        if results:
            used = attempt
            break

    filters = []
    if used[0]:
        filters.append(f'in {used[0]}')
    if used[1]:
        filters.append(f'under ৳{used[1]:,}')
    if used[2]:
        filters.append('with ' + ', '.join(used[2]))
    summary = f"I found {len(results)} hotel{'s' if len(results) != 1 else ''} {' '.join(filters)}".rstrip() + '.'
    if used != (city, max_price, amenities):
        summary = "I couldn't find an exact match, so I widened the search. " + summary
    if any(w in text for w in PLAN_WORDS):
        summary += ' Day-by-day trip planning needs the full AI assistant, which is not enabled on this server yet.'

    cards = {h.pk: h for h in Hotel.objects.filter(pk__in=[r['id'] for r in results[:4]])}
    return {
        'text': summary,
        'hotels': [hotel_card(cards[r['id']]) for r in results[:4] if r['id'] in cards],
        'quickActions': ['Show cheaper options', 'Check my bookings'],
    }
