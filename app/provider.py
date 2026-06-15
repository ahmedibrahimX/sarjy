"""LLM provider seam.

llm.py consumes this instead of the OpenAI SDK directly, so a model or
provider swap (Attack 5) happens here without touching the orchestration.
Events are raw OpenAI stream chunks for now; OpenAI is the only
implementation.
"""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)


async def stream_chat(
    oai: AsyncOpenAI,
    *,
    model: str,
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam],
) -> AsyncIterator[ChatCompletionChunk]:
    stream = await oai.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        stream=True,
    )
    async for chunk in stream:
        yield chunk
