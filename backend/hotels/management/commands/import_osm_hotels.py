"""
Import hotels, resorts, guest houses and motels in Bangladesh from OpenStreetMap
(via the Overpass API) as claimable listings: visible in search and AI
recommendations, not bookable until an owner claims them and adds rooms/photos.

    python manage.py import_osm_hotels                 # download and import
    python manage.py import_osm_hotels --from-cache    # re-import the last download
    python manage.py import_osm_hotels --limit 50      # try it on a few first

Data © OpenStreetMap contributors, available under the Open Database License (ODbL).
Re-running is safe: listings are matched by OSM id; claimed listings are never overwritten.
"""

import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from hotels.models import Hotel

OVERPASS_ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
]
OVERPASS_QUERY = """[out:json][timeout:120];
area["ISO3166-1"="BD"][admin_level=2]->.bd;
(nwr["tourism"~"^(hotel|resort|guest_house|motel)$"]["name"](area.bd););
out tags center;"""
CACHE_FILE = Path(settings.BASE_DIR) / 'data' / 'osm_hotels_bd.json'
USER_AGENT = 'LuminaStay/0.1 (hotel listings import; https://www.openstreetmap.org/copyright)'

# City/town centres used to name the area of listings without an addr:city tag
BD_PLACES = [
    ('Dhaka', 23.8103, 90.4125), ('Chattogram', 22.3569, 91.7832), ("Cox's Bazar", 21.4272, 92.0058),
    ('Sylhet', 24.8949, 91.8687), ('Sreemangal', 24.3065, 91.7296), ('Khulna', 22.8456, 89.5403),
    ('Rajshahi', 24.3745, 88.6042), ('Barishal', 22.7010, 90.3535), ('Rangpur', 25.7439, 89.2752),
    ('Mymensingh', 24.7471, 90.4203), ('Cumilla', 23.4607, 91.1809), ('Bogura', 24.8466, 89.3776),
    ('Jashore', 23.1664, 89.2081), ('Kuakata', 21.8167, 90.1210), ('Bandarban', 22.1953, 92.2184),
    ('Rangamati', 22.6574, 92.1735), ('Khagrachari', 23.1193, 91.9847), ('Sajek Valley', 23.3820, 92.2938),
    ("Saint Martin's Island", 20.6237, 92.3234), ('Teknaf', 20.8624, 92.3058), ('Gazipur', 23.9999, 90.4203),
    ('Narayanganj', 23.6238, 90.5000), ('Tangail', 24.2513, 89.9167), ('Dinajpur', 25.6217, 88.6355),
    ('Kushtia', 23.9013, 89.1203), ('Pabna', 24.0064, 89.2372), ('Feni', 23.0159, 91.3976),
    ('Noakhali', 22.8696, 91.0995), ('Moulvibazar', 24.4829, 91.7774), ('Habiganj', 24.3749, 91.4155),
    ('Sunamganj', 25.0658, 91.3950), ('Chandpur', 23.2333, 90.6713), ('Faridpur', 23.6070, 89.8429),
    ('Jamalpur', 24.9375, 89.9372), ('Brahmanbaria', 23.9571, 91.1119), ('Satkhira', 22.7185, 89.0705),
    ('Patuakhali', 22.3596, 90.3299), ('Bhola', 22.6859, 90.6482), ('Natore', 24.4206, 89.0003),
    ('Thakurgaon', 26.0337, 88.4617), ('Gopalganj', 23.0050, 89.8266), ('Madaripur', 23.1641, 90.1897),
    ('Kishoreganj', 24.4449, 90.7766), ('Netrokona', 24.8835, 90.7279), ('Sirajganj', 24.4534, 89.7007),
    ('Chuadanga', 23.6402, 88.8418), ('Magura', 23.4873, 89.4198), ('Narsingdi', 23.9322, 90.7154),
    ('Munshiganj', 23.5422, 90.5305), ('Lalmonirhat', 25.9923, 89.2847), ('Kurigram', 25.8072, 89.6295),
    ('Nilphamari', 25.9310, 88.8560), ('Gaibandha', 25.3288, 89.5280), ('Joypurhat', 25.0968, 89.0227),
    ('Naogaon', 24.7936, 88.9318), ('Chapainawabganj', 24.5965, 88.2775), ('Meherpur', 23.7622, 88.6318),
    ('Jhenaidah', 23.5450, 89.1726), ('Narail', 23.1725, 89.5127), ('Bagerhat', 22.6516, 89.7859),
    ('Mongla', 22.4890, 89.5950), ('Pirojpur', 22.5841, 89.9720), ('Jhalokati', 22.6406, 90.1987),
    ('Barguna', 22.1591, 90.1119), ('Lakshmipur', 22.9447, 90.8282), ('Shariatpur', 23.2423, 90.4348),
    ('Rajbari', 23.7574, 89.6440), ('Manikganj', 23.8644, 90.0047), ('Sherpur', 25.0205, 90.0153),
    ('Panchagarh', 26.3411, 88.5541), ('Kaptai', 22.4947, 92.2167),
]
CITY_ALIASES = {
    'chittagong': 'Chattogram', 'bogra': 'Bogura', 'jessore': 'Jashore', 'comilla': 'Cumilla',
    'barisal': 'Barishal', 'srimangal': 'Sreemangal', 'sreemongol': 'Sreemangal', 'coxs bazar': "Cox's Bazar",
    "cox's bazar": "Cox's Bazar", 'cox bazar': "Cox's Bazar", 'dhaka city': 'Dhaka',
}
KNOWN_CITIES = {name.lower(): name for name, _, _ in BD_PLACES}
TYPE_LABELS = {'hotel': 'Hotel', 'resort': 'Resort', 'guest_house': 'Guest house', 'motel': 'Motel'}
NAME_NOISE = re.compile(r'\b(hotel|resort|guest ?house|motel|and|&|spa|the|ltd|limited|international|intl)\b')


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def nearest_place(lat, lng) -> tuple[str, float]:
    name, plat, plng = min(BD_PLACES, key=lambda p: haversine_km(lat, lng, p[1], p[2]))
    return name, haversine_km(lat, lng, plat, plng)


def name_key(name: str) -> str:
    """Name without generic words/punctuation, for duplicate detection."""
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', NAME_NOISE.sub(' ', name.lower())).split())


def resolve_city(tags: dict, lat: float, lng: float) -> tuple[str, bool]:
    """Returns (city, is_near) — is_near when the city was inferred from coordinates."""
    raw = (tags.get('addr:city') or tags.get('addr:district') or '').strip()
    key = raw.lower().replace('’', "'")
    if key in CITY_ALIASES:
        return CITY_ALIASES[key], False
    if key in KNOWN_CITIES:
        return KNOWN_CITIES[key], False
    city, km = nearest_place(lat, lng)
    return city, km > 8


def amenities_from_tags(tags: dict) -> list[str]:
    amenities = []
    if tags.get('internet_access') in ('wlan', 'yes', 'wifi'):
        amenities.append('Free Wi-Fi' if tags.get('internet_access:fee') == 'no' else 'Wi-Fi')
    if tags.get('swimming_pool') == 'yes' or tags.get('leisure') == 'swimming_pool':
        amenities.append('Swimming pool')
    if tags.get('air_conditioning') == 'yes':
        amenities.append('Air conditioning')
    if tags.get('wheelchair') == 'yes':
        amenities.append('Wheelchair accessible')
    if tags.get('restaurant') == 'yes':
        amenities.append('Restaurant')
    if tags.get('parking') in ('yes', 'surface', 'underground'):
        amenities.append('Parking')
    return amenities


def listing_from_element(el: dict) -> dict | None:
    tags = el.get('tags', {})
    name = (tags.get('name:en') or tags.get('name') or '').strip()
    point = el.get('center') or el
    lat, lng = point.get('lat'), point.get('lon')
    if not name or lat is None or lng is None or len(name) > 200:
        return None

    city, is_near = resolve_city(tags, lat, lng)
    street = ' '.join(filter(None, [tags.get('addr:housenumber'), tags.get('addr:street')])).strip()
    area = tags.get('addr:suburb') or tags.get('addr:place') or ''
    location = ', '.join(filter(None, [street, area, city])) if (street or area) else (f'Near {city}' if is_near else city)

    kind = TYPE_LABELS.get(tags.get('tourism'), 'Hotel')
    stars = tags.get('stars', '')[:1]
    website = tags.get('website') or tags.get('contact:website') or ''
    description = (tags.get('description') or '').strip()
    if len(description) < 40:
        description = (f'{kind} in {location}. Listed from OpenStreetMap — prices, rooms and online booking are not '
                       f'available until the owner joins LuminaStay.')

    return {
        'external_id': f"osm:{el['type']}/{el['id']}",
        'name': name,
        'city': city,
        'location': location[:255],
        'description': description[:3000],
        'amenities': amenities_from_tags(tags),
        'latitude': round(lat, 6),
        'longitude': round(lng, 6),
        'stars': int(stars) if stars.isdigit() and 1 <= int(stars) <= 5 else None,
        'phone': (tags.get('phone') or tags.get('contact:phone') or '')[:40],
        'website': website[:300] if website.startswith(('http://', 'https://')) else '',
    }


class Command(BaseCommand):
    help = 'Import Bangladesh hotels from OpenStreetMap as claimable (not yet bookable) listings.'

    def add_arguments(self, parser):
        parser.add_argument('--from-cache', action='store_true', help=f'Use the last download ({CACHE_FILE.name}).')
        parser.add_argument('--limit', type=int, default=0, help='Import at most this many listings.')

    def fetch(self) -> dict:
        body = urllib.parse.urlencode({'data': OVERPASS_QUERY}).encode()
        errors = []
        for url in OVERPASS_ENDPOINTS:
            self.stdout.write(f'Downloading from {url} …')
            try:
                request = urllib.request.Request(url, data=body, headers={'User-Agent': USER_AGENT})
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = json.load(response)
                CACHE_FILE.parent.mkdir(exist_ok=True)
                CACHE_FILE.write_text(json.dumps(data), encoding='utf-8')
                return data
            except Exception as exc:  # network errors, 429/5xx from busy mirrors
                errors.append(f'{url}: {exc}')
        raise CommandError('Every Overpass server failed:\n' + '\n'.join(errors))

    def handle(self, *args, from_cache=False, limit=0, **options):
        if from_cache:
            if not CACHE_FILE.exists():
                raise CommandError(f'No cached download at {CACHE_FILE}; run without --from-cache first.')
            data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        else:
            data = self.fetch()

        listings = [item for item in (listing_from_element(el) for el in data.get('elements', [])) if item]
        if limit:
            listings = listings[:limit]

        # Existing non-imported hotels, to link instead of duplicating (similar name, < 1.5 km apart)
        existing = [h for h in Hotel.objects.exclude(source=Hotel.Source.OSM).exclude(latitude=None)
                    if not h.external_id]

        # The same hotel is often mapped twice in OSM (a point and a building outline): keep one
        seen: list[tuple[str, float, float]] = [
            (name_key(h.name), float(h.latitude), float(h.longitude))
            for h in Hotel.objects.filter(source=Hotel.Source.OSM).exclude(latitude=None)
        ]

        created = updated = linked = skipped = duplicates = 0
        with transaction.atomic():
            for item in listings:
                current = Hotel.objects.filter(external_id=item['external_id']).first()
                key = name_key(item['name']) or item['name'].lower()
                if current is None and any(k == key and haversine_km(item['latitude'], item['longitude'], lat, lng) < 0.3
                                           for k, lat, lng in seen):
                    duplicates += 1
                    continue
                seen.append((key, item['latitude'], item['longitude']))
                if current is not None:
                    if current.owner_id or current.source != Hotel.Source.OSM:
                        skipped += 1  # claimed or linked: the owner's data wins
                        continue
                    for field, value in item.items():
                        setattr(current, field, value)
                    current.save()
                    updated += 1
                    continue

                match = next((h for h in existing if key and (key in name_key(h.name) or name_key(h.name) in key)
                              and haversine_km(item['latitude'], item['longitude'],
                                               float(h.latitude), float(h.longitude)) < 1.5), None)
                if match is not None:
                    match.external_id = item['external_id']
                    match.save(update_fields=['external_id'])
                    existing.remove(match)
                    linked += 1
                    continue

                Hotel.objects.create(
                    **item, source=Hotel.Source.OSM, approval_status=Hotel.Approval.APPROVED, is_active=True,
                    price_per_night=None, match_score=0, rating=0, reviews_count=0,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'OpenStreetMap import: {created} new, {updated} updated, {linked} linked to existing hotels, '
            f'{duplicates} duplicates skipped, {skipped} skipped (claimed). Data © OpenStreetMap contributors (ODbL).'
        ))
