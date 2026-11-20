"""
OpenAI-powered travel assistant: the same bounded tool-use loop as agent.py,
using Chat Completions function calling. Tools and prompt are shared.
"""

import json
import logging
from functools import lru_cache

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from .agent import MAX_TOOL_ROUNDS, SYSTEM_PROMPT, build_payload
from .tools import TOOL_DEFINITIONS, ToolContext, run_tool

logger = logging.getLogger(__name__)

OPENAI_TOOLS = [
    {
        'type': 'function',
        'function': {'name': t['name'], 'description': t['description'], 'parameters': t['input_schema']},
    }
    for t in TOOL_DEFINITIONS
]

REFUSAL_TEXT = "Sorry, I can't help with that. I'm happy to help you find hotels or plan a trip in Bangladesh."


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    # Credentials come from OPENAI_API_KEY (loaded from backend/.env)
    return OpenAI(timeout=90.0, max_retries=2)


def run_openai_assistant(history: list[dict], user=None) -> dict:
    """One assistant turn via OpenAI. Raises openai.APIError subclasses on API failure."""
    ctx = ToolContext(user=user)
    system = SYSTEM_PROMPT.format(today=timezone.localdate().strftime('%A, %d %B %Y'))
    messages: list[dict] = [{'role': 'system', 'content': system}]
    messages += [{'role': m['role'], 'content': m['text']} for m in history]
    client = get_client()
    text = ''

    for _ in range(MAX_TOOL_ROUNDS):
        completion = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            tools=OPENAI_TOOLS,
            max_completion_tokens=4000,
        )
        choice = completion.choices[0]
        message = choice.message

        if getattr(message, 'refusal', None) or choice.finish_reason == 'content_filter':
            logger.info('Assistant request declined by OpenAI (finish_reason=%s)', choice.finish_reason)
            return {'text': REFUSAL_TEXT}

        tool_calls = [c for c in (message.tool_calls or []) if c.type == 'function']
        text = (message.content or '').strip() or text

        assistant_turn: dict = {'role': 'assistant', 'content': message.content}
        if tool_calls:
            assistant_turn['tool_calls'] = [
                {'id': c.id, 'type': 'function', 'function': {'name': c.function.name, 'arguments': c.function.arguments}}
                for c in tool_calls
            ]
        messages.append(assistant_turn)

        if not tool_calls:
            if choice.finish_reason == 'length':
                logger.warning('Assistant reply hit max_completion_tokens')
            break

        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or '{}')
            except json.JSONDecodeError:
                content = json.dumps({'error': 'Arguments were not valid JSON.'})
            else:
                content, _ = run_tool(ctx, call.function.name, args)
            messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': content})
    else:
        logger.warning('Assistant stopped after %d tool rounds', MAX_TOOL_ROUNDS)

    return build_payload(ctx, text)
