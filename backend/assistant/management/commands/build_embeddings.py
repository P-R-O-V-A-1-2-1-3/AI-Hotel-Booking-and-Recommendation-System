"""
Embed hotels for semantic search (OpenAI). Re-run after adding hotels or reviews;
unchanged hotels are skipped.

    python manage.py build_embeddings [--force]
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant.embeddings import refresh_hotel_embeddings


class Command(BaseCommand):
    help = 'Create or refresh OpenAI embeddings used by the assistant\'s semantic hotel search.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-embed every hotel, even if unchanged.')

    def handle(self, *args, force=False, **options):
        if not settings.SEMANTIC_SEARCH_ENABLED:
            raise CommandError('OPENAI_API_KEY is not set in backend/.env.')
        count = refresh_hotel_embeddings(force=force)
        self.stdout.write(self.style.SUCCESS(f'Embedded {count} hotel(s) with {settings.OPENAI_EMBEDDING_MODEL}.'))
