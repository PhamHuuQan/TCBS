
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx


class CloudAIError(RuntimeError):
    pass


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


async def ask_gemini(
    question: str,
    context: str = "",
    history: list[dict[str, str]] | None = None,
    system: str | None = None,
) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise CloudAIError("Chưa cấu hình GEMINI_API_KEY trên Railway.")

    model_errors: list[str] = []
    timeout = float(os.getenv("GEMINI_TIMEOUT", "90"))
    system_text = system or (
        "Bạn là trợ lý quant chứng khoán Việt Nam. "
        "Dữ liệu TCBS là dữ liệu công cụ; tuyệt đối không bịa số liệu. "
        "Phân biệt dữ liệu live với BCTC lịch sử. "
        "Không biến điểm số heuristic thành khẳng định chắc chắn mua/bán. "
        "Trả lời tiếng Việt, rõ ràng, có cấu trúc, ưu tiên số liệu và rủi ro."
    )

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

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in _models():
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent?key={api_key}"
            )
            try:
                response = await client.post(url, json=body)
                if response.status_code in {429, 500, 502, 503, 504}:
                    model_errors.append(f"{model}: HTTP {response.status_code}")
                    await asyncio.sleep(0.8)
                    continue
                if response.status_code >= 400:
                    detail = response.text[:500]
                    model_errors.append(f"{model}: HTTP {response.status_code} {detail}")
                    continue
                text = _extract_text(response.json())
                if text:
                    return text
                model_errors.append(f"{model}: empty response")
            except Exception as exc:
                model_errors.append(f"{model}: {exc}")

    raise CloudAIError("Gemini không trả lời được. " + " | ".join(model_errors))


async def synthesize_quant(analysis: dict[str, Any]) -> str:
    compact = json.dumps(analysis, ensure_ascii=False, default=str)
    return await ask_gemini(
        "Hãy giải thích kết quả quant dưới đây cho người dùng. "
        "Nêu 3 điểm mạnh, 3 rủi ro, điều kiện cần theo dõi và kết luận cân bằng. "
        "Không tự thêm số liệu ngoài dữ liệu được cung cấp.",
        context=compact,
    )
