from __future__ import annotations
from typing import Any
from app.quant.analyzer import analyze_ticker


def compare_tickers(tickers: list[str]) -> dict[str, Any]:
    analyses = [analyze_ticker(x) for x in tickers if x.strip()]
    return {"tickers": [x["ticker"] for x in analyses], "analyses": analyses}
