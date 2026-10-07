from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx


class CloudAIError(RuntimeError):
    pass


def _split_keys(*env_names: str) -> list[str]:
    values: list[str] = []
    for name in env_names:
        raw = os.getenv(name, "")
        if not raw:
            continue
        for item in raw.replace("\n", ",").split(","):
            key = item.strip()
            if key and key not in values:
                values.append(key)
    return values


def _configured_gemini_keys() -> list[str]:
    keys = _split_keys("GEMINI_API_KEYS", "GEMINI_API_KEY")
    return [k for k in keys if not k.startswith("PENDING_")]


def _configured_xkiro_keys() -> list[str]:
    return _split_keys("XKIRO_API_KEYS", "XKIRO_API_KEY")


def _models() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    fallbacks = os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.8-flash,gemini-2.5-flash",
    ).strip()
    return [x.strip() for x in [primary, *fallbacks.split(",")] if x.strip()]


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()


def _extract_xkiro_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def _xkiro_model_rank(item: dict[str, Any]) -> tuple[int, int, int, str]:
    capabilities = item.get("capabilities") or {}
    vendor = str(item.get("owned_by") or item.get("id") or "").lower()
    reasoning = int(bool(capabilities.get("reasoning")))
    tools = int(bool(capabilities.get("tools")))
    context = int(item.get("context_length") or 0)

    vendor_bonus = 0
    for needle, bonus in (
        ("qwen", 6),
        ("mistral", 5),
        ("cohere", 4),
        ("meta", 3),
        ("meituan", 3),
        ("inclusion", 2),
        ("sense", 2),
        ("liquid", 2),
    ):
        if needle in vendor:
            vendor_bonus = bonus
            break

    return (vendor_bonus + reasoning * 3 + tools, reasoning + tools, context, str(item.get("id") or ""))


async def _list_xkiro_free_models(
    client: httpx.AsyncClient,
) -> list[str]:
    response = await client.get("https://api.xkiro.com/v1/models")
    if response.status_code >= 400:
        raise CloudAIError(f"xKiro /v1/models HTTP {response.status_code}")
    payload = response.json()
    data = payload.get("data") or []
    free = [
        item for item in data
        if isinstance(item, dict)
        and item.get("access_tier") == "free"
        and item.get("id")
    ]
    free.sort(key=_xkiro_model_rank, reverse=True)

    allowlist = {
        x.strip() for x in os.getenv("XKIRO_MODEL_ALLOWLIST", "").split(",") if x.strip()
    }
    if allowlist:
        free = [item for item in free if item.get("id") in allowlist]

    limit = max(1, int(os.getenv("XKIRO_MAX_FREE_MODELS", "12")))
    return [str(item["id"]) for item in free[:limit]]


async def _xkiro_free_remaining(client: httpx.AsyncClient, api_key: str) -> int | None:
    try:
        response = await client.get(
            "https://api.xkiro.com/v1/usage",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        free_tokens = payload.get("free_tokens") or {}
        remaining = free_tokens.get("remaining")
        return int(remaining) if remaining is not None else None
    except Exception:
        return None


async def _ask_xkiro(
    question: str,
    context: str,
    history: list[dict[str, str]] | None,
    system: str,
) -> str:
    keys = _configured_xkiro_keys()
    if not keys:
        raise CloudAIError("Chưa cấu hình XKIRO_API_KEY trên Railway.")

    timeout = float(os.getenv("XKIRO_TIMEOUT", "90"))
    max_tokens = int(os.getenv("XKIRO_MAX_OUTPUT_TOKENS", os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1400")))
    temperature = float(os.getenv("XKIRO_TEMPERATURE", os.getenv("GEMINI_TEMPERATURE", "0.2")))

    contents: list[dict[str, Any]] = []
    for item in (history or [])[-8:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "content": item["content"]})

    user_text = question
    if context:
        user_text += "\n\n=== DỮ LIỆU THAM KHẢO ===\n" + context
    contents.append({"role": "user", "content": user_text})

    async with httpx.AsyncClient(timeout=timeout) as client:
        models = await _list_xkiro_free_models(client)
        if not models:
            raise CloudAIError("xKiro không có model free khả dụng trong catalog hiện tại.")

        last_errors: list[str] = []

        for key_index, api_key in enumerate(keys):
            remaining = await _xkiro_free_remaining(client, api_key)
            if remaining is not None and remaining <= 0:
                last_errors.append(f"key#{key_index + 1}: free_tokens=0")
                continue

            for model in models:
                body = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        *contents,
                    ],
                    "max_tokens": max_tokens,
                }
                if temperature > 0:
                    body["temperature"] = temperature

                try:
                    response = await client.post(
                        "https://api.xkiro.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                await asyncio.sleep(min(float(retry_after), 3.0))
                            except ValueError:
                                pass
                        last_errors.append(f"key#{key_index + 1}/{model}: HTTP {response.status_code}")
                        continue
                    if response.status_code in {401, 403}:
                        last_errors.append(f"key#{key_index + 1}/{model}: HTTP {response.status_code}")
                        break
                    if response.status_code >= 400:
                        last_errors.append(
                            f"key#{key_index + 1}/{model}: HTTP {response.status_code} {response.text[:220]}"
                        )
                        continue

                    text = _extract_xkiro_text(response.json())
                    if text:
                        return text
                    last_errors.append(f"key#{key_index + 1}/{model}: empty response")
                except Exception as exc:
                    last_errors.append(f"key#{key_index + 1}/{model}: {exc}")

    raise CloudAIError("xKiro không trả lời được. " + " | ".join(last_errors[-20:]))


async def _ask_gemini(
    question: str,
    context: str,
    history: list[dict[str, str]] | None,
    system_text: str,
) -> str:
    keys = _configured_gemini_keys()
    if not keys:
        raise CloudAIError("Chưa cấu hình GEMINI_API_KEY trên Railway.")

    timeout = float(os.getenv("GEMINI_TIMEOUT", "90"))
    contents: list[dict[str, Any]] = []
    for item in (history or [])[-8:]:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})

    user_text = question
    if context:
        user_text += "\n\n=== DỮ LIỆU THAM KHẢO ===\n" + context
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1400")),
        },
    }

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for key_index, api_key in enumerate(keys):
            for model in _models():
                url = (
                    "https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{model}:generateContent?key={api_key}"
                )
                try:
                    response = await client.post(url, json=body)
                    if response.status_code in {429, 500, 502, 503, 504}:
                        errors.append(f"key#{key_index + 1}/{model}: HTTP {response.status_code}")
                        await asyncio.sleep(0.8)
                        continue
                    if response.status_code >= 400:
                        errors.append(
                            f"key#{key_index + 1}/{model}: HTTP {response.status_code} {response.text[:220]}"
                        )
                        continue
                    text = _extract_text(response.json())
                    if text:
                        return text
                    errors.append(f"key#{key_index + 1}/{model}: empty response")
                except Exception as exc:
                    errors.append(f"key#{key_index + 1}/{model}: {exc}")

    raise CloudAIError("Gemini không trả lời được. " + " | ".join(errors[-20:]))


async def ask_gemini(
    question: str,
    context: str = "",
    history: list[dict[str, str]] | None = None,
    system: str | None = None,
) -> str:
    system_text = system or (
        "Bạn là trợ lý quant chứng khoán Việt Nam. "
        "Dữ liệu TCBS là dữ liệu công cụ; tuyệt đối không bịa số liệu. "
        "Phân biệt dữ liệu live với BCTC lịch sử. "
        "Không biến điểm số heuristic thành khẳng định chắc chắn mua/bán. "
        "Trả lời tiếng Việt, rõ ràng, có cấu trúc, ưu tiên số liệu và rủi ro."
    )

    providers = [
        x.strip().lower()
        for x in os.getenv("AI_PROVIDER_ORDER", "gemini,xkiro").split(",")
        if x.strip()
    ]
    errors: list[str] = []

    for provider in providers:
        try:
            if provider == "xkiro":
                return await _ask_xkiro(question, context, history, system_text)
            if provider == "gemini":
                return await _ask_gemini(question, context, history, system_text)
        except CloudAIError as exc:
            errors.append(f"{provider}: {exc}")

    raise CloudAIError("Không có AI provider nào trả lời được. " + " | ".join(errors))


async def synthesize_quant(analysis: dict[str, Any]) -> str:
    compact = json.dumps(analysis, ensure_ascii=False, default=str)
    return await ask_gemini(
        "Hãy giải thích kết quả quant dưới đây cho người dùng. "
        "Nêu 3 điểm mạnh, 3 rủi ro, điều kiện cần theo dõi và kết luận cân bằng. "
        "Không tự thêm số liệu ngoài dữ liệu được cung cấp.",
        context=compact,
    )
