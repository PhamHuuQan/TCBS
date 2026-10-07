from __future__ import annotations

from typing import Any
from app.quant.analyzer import analyze_ticker


def screen_tickers(tickers: list[str]) -> dict[str, Any]:
    results = []
    errors = []
    for raw in tickers:
        ticker = raw.upper().strip()
        if not ticker: continue
        try:
            results.append(analyze_ticker(ticker))
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
    results.sort(key=lambda x: x.get("score") if x.get("score") is not None else -1, reverse=True)
    return {"results": results, "errors": errors, "count": len(results)}
