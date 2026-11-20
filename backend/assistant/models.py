from django.db import models

from hotels.models import Hotel


class HotelEmbedding(models.Model):
    """
    OpenAI embedding of a hotel's description, amenities and reviews, used for
    semantic search ("best deshi breakfast", "quiet place for a honeymoon").
    Stored as JSON and compared in Python; swap for pgvector once the extension is installed.
    """

    hotel = models.OneToOneField(Hotel, on_delete=models.CASCADE, related_name='embedding')
    model = models.CharField(max_length=100)
    vector = models.JSONField()
    source_hash = models.CharField(max_length=64, help_text='SHA-256 of the embedded text; unchanged text is skipped')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Embedding for {self.hotel.name}'
