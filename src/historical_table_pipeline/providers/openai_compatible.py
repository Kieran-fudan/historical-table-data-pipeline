"""OpenAI-compatible vision OCR adapter with an explicit network safety gate."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from historical_table_pipeline.config import Profile
from historical_table_pipeline.io import canonical_json, sha256_file


class OcrProviderError(RuntimeError):
    """Raised when a provider response cannot satisfy the transcription contract."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    engine_id: str
    model: str
    api_key_env: str
    base_url: str | None = None
    max_attempts: int = 4
    timeout_seconds: float = 120.0


def build_system_prompt(profile: Profile) -> str:
    fields = [
        {
            "name": item.name,
            "label": item.label,
            "type": item.data_type,
            "required": item.required,
        }
        for item in profile.fields
    ]
    profile_ocr = profile.raw.get("ocr", {})
    extra = profile_ocr.get("instructions", []) if isinstance(profile_ocr, dict) else []
    if isinstance(extra, str):
        extra = [extra]
    contract = {
        "rows": [
            {
                "source_row_index": 0,
                "table_id": "main",
                "printed_page_label": None,
                "cells": {item.name: "verbatim source text or null" for item in profile.fields},
            }
        ]
    }
    return (
        "Transcribe the table image into JSON only. Preserve source wording, punctuation, "
        "leading zeroes, units, currency markers, ditto marks, blanks, titles, totals, and "
        "uncertainty. Do not translate, standardize, infer missing values, convert currencies, "
        "or silently drop non-data rows. Keep visual row order. Return exactly one top-level "
        "object matching the contract below.\n\n"
        f"Fields:\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n\n"
        f"Source-specific instructions:\n{json.dumps(list(extra), ensure_ascii=False, indent=2)}"
        f"\n\nContract example:\n{json.dumps(contract, ensure_ascii=False, indent=2)}"
    )


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _strip_fence(text: str) -> str:
    match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, flags=re.DOTALL)
    return match.group(1) if match else text.strip()


def parse_response(text: str, profile: Profile) -> list[dict[str, Any]]:
    try:
        value = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise OcrProviderError(f"Provider did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise OcrProviderError("Provider response must contain a top-level rows list")
    output: list[dict[str, Any]] = []
    allowed = set(profile.field_names)
    for index, raw_row in enumerate(value["rows"]):
        if not isinstance(raw_row, dict) or not isinstance(raw_row.get("cells"), dict):
            raise OcrProviderError(f"rows[{index}] must contain a cells object")
        unknown = set(str(key) for key in raw_row["cells"]) - allowed
        if unknown:
            raise OcrProviderError(
                f"rows[{index}] contains fields not declared by the profile: {sorted(unknown)}"
            )
        cells = {
            field_name: raw_row["cells"].get(field_name)
            for field_name in profile.field_names
        }
        output.append(
            {
                "source_row_index": int(raw_row.get("source_row_index", index)),
                "table_id": str(raw_row.get("table_id", "main")),
                "printed_page_label": raw_row.get("printed_page_label"),
                "cells": cells,
            }
        )
    return output


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
        if parts:
            return "\n".join(parts)
    raise OcrProviderError("Provider returned an unsupported message content shape")


def transcribe_page(
    image_path: str | Path,
    *,
    profile: Profile,
    provider: OpenAICompatibleConfig,
    document_id: str,
    source_pdf_page_index: int,
    allow_network: bool,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    if not allow_network:
        raise OcrProviderError(
            "Network OCR is disabled. Re-run with explicit --allow-network after reviewing "
            "provider privacy, cost, and data-handling terms."
        )
    image = Path(image_path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(image)
    key = os.environ.get(provider.api_key_env, "")
    if client is None and not key:
        raise OcrProviderError(
            f"Required credential environment variable is not set: {provider.api_key_env}"
        )
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OcrProviderError(
                "OCR requires the optional 'ocr' extra: "
                "pip install 'historical-table-data-pipeline[ocr]'"
            ) from exc
        client = OpenAI(
            api_key=key,
            base_url=provider.base_url,
            timeout=provider.timeout_seconds,
        )
    prompt = build_system_prompt(profile)
    last_error: BaseException | None = None
    response = None
    for attempt in range(provider.max_attempts):
        try:
            response = client.chat.completions.create(
                model=provider.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe this page."},
                            {
                                "type": "image_url",
                                "image_url": {"url": _image_data_url(image)},
                            },
                        ],
                    },
                ],
            )
            break
        except Exception as exc:  # provider SDKs expose different transient exception types
            last_error = exc
            if attempt + 1 >= provider.max_attempts:
                raise OcrProviderError(
                    f"OCR provider failed after {provider.max_attempts} attempts: {exc}"
                ) from exc
            time.sleep(min(2**attempt, 8))
    if response is None:
        raise OcrProviderError(f"OCR provider did not return a response: {last_error}")
    text = _message_text(response.choices[0].message.content)
    rows = parse_response(text, profile)
    response_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    common = {
        "document_id": document_id,
        "page_id": f"{document_id}:pdf:{source_pdf_page_index:06d}",
        "source_pdf_page_index": source_pdf_page_index,
        "engine_id": provider.engine_id,
        "engine_version": provider.model,
        "prompt_hash": prompt_sha256(prompt),
        "response_hash": response_hash,
        "image_sha256": sha256_file(image),
    }
    return [{**common, **row} for row in rows]


def provider_config_from_profile(profile: Profile, engine_id: str) -> OpenAICompatibleConfig:
    ocr = profile.raw.get("ocr", {})
    engines = ocr.get("engines", []) if isinstance(ocr, dict) else []
    for engine in engines:
        if isinstance(engine, dict) and str(engine.get("id")) == engine_id:
            if str(engine.get("type", "openai-compatible")) != "openai-compatible":
                raise OcrProviderError(f"Engine {engine_id!r} is not OpenAI-compatible")
            required = ["model", "api_key_env"]
            missing = [name for name in required if not str(engine.get(name, "")).strip()]
            if missing:
                raise OcrProviderError(
                    f"Engine {engine_id!r} is missing: {', '.join(missing)}"
                )
            return OpenAICompatibleConfig(
                engine_id=engine_id,
                model=str(engine["model"]),
                api_key_env=str(engine["api_key_env"]),
                base_url=str(engine["base_url"]) if engine.get("base_url") else None,
                max_attempts=int(engine.get("max_attempts", 4)),
                timeout_seconds=float(engine.get("timeout_seconds", 120)),
            )
    raise OcrProviderError(f"Unknown OCR engine in profile: {engine_id}")


def prompt_contract_fingerprint(profile: Profile) -> str:
    """Expose a stable fingerprint for manifests and prompt-drift tests."""

    content = canonical_json({"prompt": build_system_prompt(profile)}).encode()
    return hashlib.sha256(content).hexdigest()
