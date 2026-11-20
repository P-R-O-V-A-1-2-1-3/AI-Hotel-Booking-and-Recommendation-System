"""
Streaming chat (Server-Sent Events): the reply appears word by word, with short
status lines while tools run, then the cards in a final "done" event.

    POST /api/ai/chat/stream/   {messages: [{role, text}]}
    → text/event-stream of:
        data: {"type": "status", "text": "Searching hotels in Sylhet…"}
        data: {"type": "delta",  "text": "Here are"}
        data: {"type": "done",   "hotels": [...], "itinerary": {...}, "quickActions": [...], "mode": "ai"}
        data: {"type": "error",  "text": "..."}   (only if the stream breaks midway)

OpenAI replies are streamed live; Claude and the rule-based fallback are
produced whole and then "typed" out in small chunks so the UI behaves the same.
"""

import json
import logging
import re
import time

import anthropic
import openai
from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import permissions
from rest_framework.views import APIView

from .agent import MAX_TOOL_ROUNDS, SYSTEM_PROMPT, build_payload, run_assistant
from .fallback import run_fallback
from .openai_agent import OPENAI_TOOLS, REFUSAL_TEXT, get_client
from .tools import ToolContext, run_tool
from .views import AssistantAnonThrottle, AssistantUserThrottle, ChatRequestSerializer

logger = logging.getLogger(__name__)

TYPING_DELAY_SECONDS = 0.02  # pacing for replies that weren't generated as a stream


def tool_status(name: str, args: dict) -> str | None:
    """Friendly progress line shown while a tool runs (display tools stay silent)."""
    city = args.get('city') if isinstance(args, dict) else None
    return {
        'search_hotels': f'Searching hotels{f" in {city}" if city else ""}…',
        'semantic_search_hotels': 'Reading guest reviews for the best matches…',
        'get_hotel_details': 'Checking rooms and reviews…',
        'check_availability': 'Checking availability and prices…',
        'get_my_bookings': 'Looking up your bookings…',
        'show_itinerary': 'Planning your itinerary…',
    }.get(name)


def stream_openai(history: list[dict], user=None):
    """Yields chat events while running the OpenAI tool loop with streaming enabled."""
    ctx = ToolContext(user=user)
    system = SYSTEM_PROMPT.format(today=timezone.localdate().strftime('%A, %d %B %Y'))
    messages: list[dict] = [{'role': 'system', 'content': system}]
    messages += [{'role': m['role'], 'content': m['text']} for m in history]
    client = get_client()
    wrote_text = False

    for _ in range(MAX_TOOL_ROUNDS):
        stream = client.chat.completions.create(
            model=settings.OPENAI_MODEL, messages=messages, tools=OPENAI_TOOLS,
            max_completion_tokens=4000, stream=True,
        )
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish_reason = None
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, 'refusal', None):
                yield {'type': 'delta', 'text': REFUSAL_TEXT}
                yield {'type': 'done', 'mode': 'ai'}
                return
            if delta.content:
                if not text_parts and wrote_text:
                    yield {'type': 'delta', 'text': '\n\n'}  # separate a lead-in from the answer
                text_parts.append(delta.content)
                yield {'type': 'delta', 'text': delta.content}
            # Tool calls arrive in fragments keyed by index; stitch them together
            for tc in delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {'id': '', 'name': '', 'arguments': ''})
                slot['id'] = tc.id or slot['id']
                if tc.function is not None:
                    slot['name'] += tc.function.name or ''
                    slot['arguments'] += tc.function.arguments or ''
            finish_reason = choice.finish_reason or finish_reason

        if finish_reason == 'content_filter':
            yield {'type': 'delta', 'text': REFUSAL_TEXT}
            break
        wrote_text = wrote_text or bool(text_parts)

        ordered = [calls[i] for i in sorted(calls)]
        turn: dict = {'role': 'assistant', 'content': ''.join(text_parts) or None}
        if ordered:
            turn['tool_calls'] = [{'id': c['id'], 'type': 'function',
                                   'function': {'name': c['name'], 'arguments': c['arguments']}} for c in ordered]
        messages.append(turn)
        if not ordered:
            break

        for call in ordered:
            try:
                args = json.loads(call['arguments'] or '{}')
            except json.JSONDecodeError:
                content = json.dumps({'error': 'Arguments were not valid JSON.'})
            else:
                status = tool_status(call['name'], args)
                if status:
                    yield {'type': 'status', 'text': status}
                content, _ = run_tool(ctx, call['name'], args)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': content})
    else:
        logger.warning('Streaming assistant stopped after %d tool rounds', MAX_TOOL_ROUNDS)

    cards = build_payload(ctx, '')
    cards.pop('text', None)
    yield {'type': 'done', **cards, 'mode': 'ai'}


def typed(payload: dict, mode: str):
    """Emit an already-complete reply as small chunks, so it reads like typing."""
    payload = dict(payload)
    text = payload.pop('text', '') or ''
    for piece in re.findall(r'\S+\s*', text):
        yield {'type': 'delta', 'text': piece}
        time.sleep(TYPING_DELAY_SECONDS)
    yield {'type': 'done', **payload, 'mode': mode}


def sse(event: dict) -> str:
    return f'data: {json.dumps(event, ensure_ascii=False)}\n\n'


class ChatStreamView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AssistantAnonThrottle, AssistantUserThrottle]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        history = serializer.validated_data['messages']
        user = request.user if request.user.is_authenticated else None

        def events():
            started = False
            try:
                if settings.AI_ASSISTANT_ENABLED and settings.AI_PROVIDER == 'openai':
                    try:
                        for event in stream_openai(history, user):
                            started = True
                            yield sse(event)
                        return
                    except openai.APIError as exc:
                        logger.error('OpenAI stream failed (%s): %s', type(exc).__name__, exc)
                        if started:
                            yield sse({'type': 'error', 'text': 'The connection to the AI dropped. Please try again.'})
                            return
                elif settings.AI_ASSISTANT_ENABLED:
                    try:
                        yield from map(sse, typed(run_assistant(history, user), 'ai'))
                        return
                    except anthropic.APIError as exc:
                        logger.error('Claude request failed (%s): %s', type(exc).__name__, exc)
                # No AI configured, or it failed before saying anything: rule-based answer
                yield from map(sse, typed(run_fallback(history, user), 'basic'))
            except Exception:
                logger.exception('Chat stream crashed')
                yield sse({'type': 'error', 'text': 'Something went wrong. Please try again.'})

        response = StreamingHttpResponse(events(), content_type='text/event-stream; charset=utf-8')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # don't let proxies buffer the stream
        return response
