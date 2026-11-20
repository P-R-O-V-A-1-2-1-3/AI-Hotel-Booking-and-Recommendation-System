"""
Semantic hotel search with OpenAI embeddings. Each hotel is embedded from its
description, amenities, guest sentiment and recent reviews; queries are ranked
by cosine similarity.
"""

import hashlib
import math

from django.conf import settings

from hotels.models import Hotel

from .models import HotelEmbedding


def hotel_document(hotel: Hotel) -> str:
    reviews = hotel.reviews.filter(is_flagged=False)[:10]
    parts = [
        f'{hotel.name} in {hotel.location}, {hotel.city}.',
        hotel.description,
        'Amenities: ' + ', '.join(hotel.amenities) + '.',
        'Rooms: ' + ', '.join(r.name for r in hotel.rooms.all()) + '.',
        hotel.ai_sentiment_summary,
        *(f'Guest review ({r.traveler_type}, {r.rating}/5): {r.title}. {r.comment}' for r in reviews),
    ]
    return '\n'.join(p for p in parts if p)


def embed(texts: list[str]) -> list[list[float]]:
    from .openai_agent import get_client  # same configured OpenAI client
    response = get_client().embeddings.create(model=settings.OPENAI_EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


def refresh_hotel_embeddings(force: bool = False) -> int:
    """Embed active hotels whose text changed since last time. Returns how many were (re)embedded."""
    pending = []
    for hotel in Hotel.objects.filter(is_active=True).prefetch_related('rooms'):
        doc = hotel_document(hotel)
        digest = hashlib.sha256(f'{settings.OPENAI_EMBEDDING_MODEL}\n{doc}'.encode()).hexdigest()
        existing = getattr(hotel, 'embedding', None)
        if force or existing is None or existing.source_hash != digest:
            pending.append((hotel, doc, digest))

    for start in range(0, len(pending), 64):
        batch = pending[start:start + 64]
        for (hotel, _, digest), vector in zip(batch, embed([doc for _, doc, _ in batch])):
            HotelEmbedding.objects.update_or_create(
                hotel=hotel,
                defaults={'model': settings.OPENAI_EMBEDDING_MODEL, 'vector': vector, 'source_hash': digest},
            )
    return len(pending)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def semantic_search(query: str, limit: int = 5) -> list[tuple[Hotel, float]]:
    stored = list(
        HotelEmbedding.objects.filter(hotel__is_active=True, model=settings.OPENAI_EMBEDDING_MODEL)
        .select_related('hotel')
    )
    if not stored:
        return []
    query_vector = embed([query])[0]
    ranked = sorted(((e.hotel, _cosine(query_vector, e.vector)) for e in stored), key=lambda x: x[1], reverse=True)
    return ranked[:limit]
