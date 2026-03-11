import json

from api.src.services.llm_limits import (
    MIN_CONTENT_CHARS,
    budgeted_content_chars,
    chunk_text,
    estimate_tokens,
    is_context_limit_error,
)
from api.src.services.llm_prompts import build_chunk_prompt, build_merge_prompt, build_prompt


def test_estimate_tokens_uses_configured_ratio() -> None:
    assert estimate_tokens("abcd") == 4


def test_budgeted_content_chars_respects_minimum_floor() -> None:
    def huge_prompt(_schema: object, _text: object) -> str:
        return "x" * 999_999

    assert budgeted_content_chars(huge_prompt, {}, "") == MIN_CONTENT_CHARS


def test_chunk_text_splits_long_single_paragraph() -> None:
    text = "A" * 25
    chunks = chunk_text(text, max_chars=10)

    assert len(chunks) > 1
    assert "".join(chunks).replace("\n", "") == text
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_chunk_text_returns_single_chunk_for_small_text() -> None:
    text = "short text"
    assert chunk_text(text, max_chars=100) == [text]


def test_is_context_limit_error_detects_provider_message() -> None:
    exc = ValueError("This model's maximum context length is 131072 tokens")
    assert is_context_limit_error(exc) is True


def test_is_context_limit_error_ignores_unrelated_errors() -> None:
    exc = RuntimeError("network timeout while connecting")
    assert is_context_limit_error(exc) is False


def test_build_prompt_contains_schema_and_document() -> None:
    prompt = build_prompt({"field": "value"}, "hello world")
    assert "EXTRACTION SCHEMA:" in prompt
    assert "DOCUMENT TEXT:" in prompt
    assert "hello world" in prompt


def test_build_chunk_prompt_includes_chunk_indices() -> None:
    prompt = build_chunk_prompt({"a": 1}, "chunk body", 2, 5)
    assert "chunk 2 of 5" in prompt
    assert "DOCUMENT CHUNK (2/5):" in prompt


def test_build_merge_prompt_uses_compact_json_partials() -> None:
    partials = [{"a": 1}, {"b": 2}]
    prompt = build_merge_prompt({"schema": "x"}, partials)

    compact = json.dumps(partials, separators=(",", ":"))
    pretty = json.dumps(partials, indent=2)

    assert compact in prompt
    assert pretty not in prompt
