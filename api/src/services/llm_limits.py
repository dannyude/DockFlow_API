"""Token budgeting and chunking helpers for LLM extraction calls."""

from collections.abc import Callable

CHARS_PER_TOKEN = 4  # ~4 chars/token is the empirical average for English text
MODEL_MAX_CONTEXT_TOKENS = 131_072
PROMPT_TOKEN_BUDGET = 110_000
PROMPT_CHAR_BUDGET = PROMPT_TOKEN_BUDGET * CHARS_PER_TOKEN
PROMPT_SAFETY_MARGIN_CHARS = 2_000
MIN_CONTENT_CHARS = 4_000


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def budgeted_content_chars(prompt_builder: Callable[..., str], *builder_args: object) -> int:
    """Compute a conservative max content size for a prompt builder."""
    static_prompt = prompt_builder(*builder_args)
    available = PROMPT_CHAR_BUDGET - len(static_prompt) - PROMPT_SAFETY_MARGIN_CHARS
    return max(MIN_CONTENT_CHARS, available)


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks on paragraph boundaries, respecting max_chars."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n")
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        remaining = para

        while remaining:
            room = max_chars - current_len
            if room <= 0 and current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
                room = max_chars

            if len(remaining) + 1 <= room:
                current.append(remaining)
                current_len += len(remaining) + 1
                break

            take = max(1, room - 1)
            current.append(remaining[:take])
            current_len += take + 1
            chunks.append("\n".join(current))
            current = []
            current_len = 0
            remaining = remaining[take:]

    if current:
        chunks.append("\n".join(current))

    return chunks


def is_context_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "maximum context length" in message
        or "context limit" in message
        or "reduce the length of the messages" in message
        or "prompt budget exceeded" in message
    )
