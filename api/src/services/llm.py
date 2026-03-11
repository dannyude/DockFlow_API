"""LLM extraction orchestration with chunking, merge, and context-safety controls."""

import asyncio
import json
import logging
from collections.abc import Callable

from json_repair import repair_json
from openai import AsyncOpenAI, BadRequestError

from api.src.config_package import settings
from api.src.services.llm_limits import (
    PROMPT_TOKEN_BUDGET,
    budgeted_content_chars,
    chunk_text,
    estimate_tokens,
    is_context_limit_error,
)
from api.src.services.llm_prompts import build_chunk_prompt, build_merge_prompt, build_prompt

cfg = settings.get_settings()

# Initialize the ASYNC client
client = AsyncOpenAI(
    api_key=cfg.openai_api_key,
    base_url=cfg.openai_base_url
)
logger = logging.getLogger(__name__)

MAP_PHASE_MAX_CONCURRENCY = 5
MERGE_PHASE_MAX_CONCURRENCY = 5
ProgressCallback = Callable[[int, int, str], None]


def _group_partials_for_merge(schema: dict | list | str, partial_results: list[dict]) -> list[list[dict]]:
    """Build merge batches that fit inside the per-request prompt budget."""
    max_partials_chars = budgeted_content_chars(build_merge_prompt, schema, [])
    groups: list[list[dict]] = []
    current_group: list[dict] = []
    current_chars = 2  # []

    for partial in partial_results:
        partial_json = json.dumps(partial, separators=(",", ":"))
        partial_size = len(partial_json) + 1  # comma/newline overhead

        if partial_size > max_partials_chars:
            # Safety fallback: keep huge partial alone and let caller merge recursively.
            if current_group:
                groups.append(current_group)
                current_group = []
                current_chars = 2
            groups.append([partial])
            continue

        if current_group and current_chars + partial_size > max_partials_chars:
            groups.append(current_group)
            current_group = [partial]
            current_chars = 2 + partial_size
            continue

        current_group.append(partial)
        current_chars += partial_size

    if current_group:
        groups.append(current_group)

    return groups


# ---------------------------------------------------------------------------
# AI calls
# ---------------------------------------------------------------------------
async def _call_llm(prompt: str) -> dict:
    prompt_tokens = estimate_tokens(prompt)
    if prompt_tokens > PROMPT_TOKEN_BUDGET:
        raise ValueError(
            f"Prompt budget exceeded before LLM call: {prompt_tokens} > {PROMPT_TOKEN_BUDGET}"
        )

    response = await client.chat.completions.create(
        model=cfg.openai_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=8192,
        temperature=0,
    )
    raw_content = response.choices[0].message.content

    try:
        return json.loads(raw_content or "{}")
    except json.JSONDecodeError:
        # Best-effort salvage for truncated/unterminated model output.
        repaired = repair_json(raw_content or "{}", return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        return {"repaired_payload": repaired}


def _emit_progress(
    progress_callback: ProgressCallback | None,
    current: int,
    total: int,
    phase: str,
) -> None:
    """Emit extraction progress to an optional callback."""
    if not progress_callback:
        return
    progress_callback(current, total, phase)


async def run_extraction(
    schema: dict | list | str,
    document_text: str,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Smart extraction: single-shot for small docs, map-reduce for large ones."""

    single_shot_limit_chars = budgeted_content_chars(build_prompt, schema, "")

    if len(document_text) <= single_shot_limit_chars:
        logger.info("Single-shot extraction (%d chars)", len(document_text))
        _emit_progress(progress_callback, 1, 1, "Single-shot extraction")
        prompt = build_prompt(schema, document_text)
        return await _call_llm(prompt)

    # -- Map phase: extract from each chunk concurrently --
    chunk_limit_chars = budgeted_content_chars(build_chunk_prompt, schema, "", 1, 1)
    chunks = chunk_text(document_text, chunk_limit_chars)
    logger.info(
        "Map-reduce extraction: %d chars -> %d chunks (chunk_limit=%d)",
        len(document_text), len(chunks), chunk_limit_chars,
    )

    # Limit in-flight LLM calls during map phase to avoid request bursts.
    concurrency_limiter = asyncio.Semaphore(MAP_PHASE_MAX_CONCURRENCY)
    chunks_done = 0
    total_chunks = len(chunks)
    _emit_progress(progress_callback, 0, total_chunks, "Extracting Chunks")

    async def _extract_chunk(chunk: str, idx: int) -> dict:
        nonlocal chunks_done
        async with concurrency_limiter:
            prompt = build_chunk_prompt(schema, chunk, idx + 1, len(chunks))
            result = await _call_llm(prompt)
            chunks_done += 1
            _emit_progress(progress_callback, chunks_done, total_chunks, "Extracting Chunks")
            logger.info("Chunk %d/%d extracted", idx + 1, len(chunks))
            return result

    partial_results = await asyncio.gather(
        *[_extract_chunk(chunk, i) for i, chunk in enumerate(chunks)]
    )

    # -- Reduce phase: merge in bounded batches until one result remains --
    merge_round = 1
    merge_inputs = list(partial_results)
    merge_concurrency_limiter = asyncio.Semaphore(MERGE_PHASE_MAX_CONCURRENCY)

    async def _merge_group(group: list[dict]) -> dict:
        async with merge_concurrency_limiter:
            try:
                return await _call_llm(build_merge_prompt(schema, group))
            except (BadRequestError, ValueError) as exc:
                if not is_context_limit_error(exc):
                    raise

                # Fallback: recursively split oversized groups and merge in smaller steps.
                if len(group) <= 1:
                    logger.warning("Merge group too large even at size=1; returning partial as-is")
                    return group[0] if group else {}

                midpoint = len(group) // 2
                left, right = await asyncio.gather(
                    _merge_group(group[:midpoint]),
                    _merge_group(group[midpoint:]),
                )
                return await _merge_group([left, right])

    while len(merge_inputs) > 1:
        groups = _group_partials_for_merge(schema, merge_inputs)
        merged_groups_done = 0
        total_groups = len(groups)
        logger.info(
            "Merge round %d: reducing %d partials into %d groups",
            merge_round,
            len(merge_inputs),
            len(groups),
        )
        _emit_progress(progress_callback, 0, total_groups, f"Merging Results (round {merge_round})")

        async def _merge_group_with_progress(group: list[dict]) -> dict:
            nonlocal merged_groups_done
            merged = await _merge_group(group)
            merged_groups_done += 1
            _emit_progress(
                progress_callback,
                merged_groups_done,
                total_groups,
                f"Merging Results (round {merge_round})",
            )
            return merged

        merge_inputs = await asyncio.gather(
            *[_merge_group_with_progress(group) for group in groups]
        )
        merge_round += 1

    return merge_inputs[0] if merge_inputs else {}