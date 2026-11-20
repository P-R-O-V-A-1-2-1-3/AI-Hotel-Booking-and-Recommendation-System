import logging

import anthropic
import openai
from django.conf import settings
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from .agent import run_assistant
from .fallback import run_fallback
from .openai_agent import run_openai_assistant
from .picks import get_picks

logger = logging.getLogger(__name__)

MAX_HISTORY = 20
MAX_MESSAGE_CHARS = 2000


class ChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=['user', 'assistant'])
    text = serializers.CharField(max_length=MAX_MESSAGE_CHARS, trim_whitespace=True)


class ChatRequestSerializer(serializers.Serializer):
    messages = ChatMessageSerializer(many=True, allow_empty=False)

    def validate_messages(self, value):
        value = value[-MAX_HISTORY:]
        if value[-1]['role'] != 'user':
            raise serializers.ValidationError('The last message must be from the user.')
        return value


class AssistantAnonThrottle(AnonRateThrottle):
    scope = 'assistant_anon'


class AssistantUserThrottle(UserRateThrottle):
    scope = 'assistant_user'


class ChatView(APIView):
    """
    POST /api/ai/chat/  {messages: [{role: 'user'|'assistant', text}]}
    → {text, hotels?, itinerary?, quickActions?, mode: 'ai'|'basic'}

    Uses Claude when ANTHROPIC_API_KEY is configured; otherwise (or if the API
    is unavailable) answers with the rule-based search so the chat still works.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [AssistantAnonThrottle, AssistantUserThrottle]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        history = serializer.validated_data['messages']
        user = request.user if request.user.is_authenticated else None

        if settings.AI_ASSISTANT_ENABLED:
            run = run_openai_assistant if settings.AI_PROVIDER == 'openai' else run_assistant
            try:
                return Response({**run(history, user), 'mode': 'ai'})
            except (anthropic.AuthenticationError, openai.AuthenticationError):
                logger.error('The %s API key was rejected; check backend/.env', settings.AI_PROVIDER)
            except (anthropic.RateLimitError, openai.RateLimitError):
                logger.warning('%s rate limit hit; answering with basic search', settings.AI_PROVIDER)
            except (anthropic.APIStatusError, openai.APIStatusError) as exc:
                logger.error('%s API error %s: %s', settings.AI_PROVIDER, exc.status_code, exc.message)
            except (anthropic.APIConnectionError, openai.APIConnectionError):
                logger.warning('Could not reach the %s API; answering with basic search', settings.AI_PROVIDER)

        return Response({**run_fallback(history, user), 'mode': 'basic'})


class PicksView(APIView):
    """GET /api/ai/picks/ → personalised hotel picks with reasons (generic ranking when signed out)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(get_picks(request.user if request.user.is_authenticated else None))
