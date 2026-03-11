"""Prompt builder utilities for schema-driven document extraction."""

import json


def _schema_to_str(schema: dict | list | str) -> str:
    if isinstance(schema, str):
        return schema
    return json.dumps(schema, indent=2)


def build_prompt(schema: dict | list | str, document_text: str) -> str:
    schema_spec = _schema_to_str(schema)
    return f"""
You are a document data extraction engine.
Extract data from the document text below according to the schema provided.
Return ONLY a valid json object. No explanation, no markdown.

EXTRACTION SCHEMA:
{schema_spec}

DOCUMENT TEXT:
{document_text}
""".strip()


def build_chunk_prompt(schema: dict | list | str, chunk_text: str, chunk_num: int, total_chunks: int) -> str:
    schema_spec = _schema_to_str(schema)
    return f"""
You are a document data extraction engine.
This is chunk {chunk_num} of {total_chunks} from a large document.
Extract whatever data you can find in THIS chunk according to the schema.
Return ONLY a valid json object. Use empty strings or empty arrays for fields not found in this chunk.
No explanation, no markdown.

EXTRACTION SCHEMA:
{schema_spec}

DOCUMENT CHUNK ({chunk_num}/{total_chunks}):
{chunk_text}
""".strip()


def build_merge_prompt(schema: dict | list | str, partial_results: list[dict]) -> str:
    schema_spec = _schema_to_str(schema)
    partials_json = json.dumps(partial_results, separators=(",", ":"))
    return f"""
You are a document data extraction engine performing a final merge step.
Below are partial extraction results from multiple chunks of the same document.
Merge them into ONE final JSON object that follows the schema.
Deduplicate entries, prefer the most complete values, and combine arrays.
Return ONLY a valid json object. No explanation, no markdown.

EXTRACTION SCHEMA:
{schema_spec}

PARTIAL RESULTS TO MERGE:
{partials_json}
""".strip()
