from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.tcbs.data import collect_tcbs_snapshot
from app.quant.metrics import find_metric, pct_score, weighted_score


def _ratio(data: Any, *names: str) -> float | None:
    return find_metric(data, *names)


def _quality(snapshot: dict[str, Any]) -> float | None:
    roe = _ratio(snapshot, "roe")
    roa = _ratio(snapshot, "roa")
    margin = _ratio(snapshot, "net_margin", "netprofitmargin", "profitmargin")
    scores = [x for x in [pct_score(roe, 5, 25), pct_score(roa, 1, 5), pct_score(margin, 3, 25)] if x is not None]
    return round(sum(scores) / len(scores), 1) if scores else None


def _valuation(snapshot: dict[str, Any]) -> float | None:
    pe = _ratio(snapshot, "pe", "per")
    pb = _ratio(snapshot, "pb", "pbr")
    eps = _ratio(snapshot, "eps")
    scores = [x for x in [pct_score(pe, 5, 25, False), pct_score(pb, .5, 4, False)] if x is not None]
    if eps is not None and eps > 0: scores.append(75.0)
    return round(sum(scores) / len(scores), 1) if scores else None


def _growth(snapshot: dict[str, Any]) -> float | None:
    values = []
    for names in [("revenue_growth", "revenuegrowth", "sales_growth"), ("earnings_growth", "net_income_growth", "profit_growth"), ("eps_growth",)]:
        v = _ratio(snapshot, *names)
        if v is not None: values.append(pct_score(v, -10, 30))
    return round(sum(values) / len(values), 1) if values else None


def _momentum(snapshot: dict[str, Any]) -> float | None:
    rsi = _ratio(snapshot, "rsi")
    macd = _ratio(snapshot, "macd")
    values = []
    if rsi is not None: values.append(max(0.0, min(100.0, 100 - abs(rsi - 55) * 2)))
    if macd is not None: values.append(70.0 if macd > 0 else 30.0)
    return round(sum(values) / len(values), 1) if values else None


def _risk(snapshot: dict[str, Any]) -> float | None:
    vol = _ratio(snapshot, "volatility", "annualized_volatility")
    drawdown = _ratio(snapshot, "max_drawdown", "maximum_drawdown")
    values = []
    if vol is not None: values.append(pct_score(vol, 10, 60, False))
    if drawdown is not None: values.append(pct_score(abs(drawdown), 5, 50, False))
    return round(sum(values) / len(values), 1) if values else None


def analyze_ticker(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    snapshot = collect_tcbs_snapshot(ticker)
    categories = {
        "valuation": _valuation(snapshot),
        "quality": _quality(snapshot),
        "growth": _growth(snapshot),
        "momentum": _momentum(snapshot),
        "risk": _risk(snapshot),
    }
    score = weighted_score(categories)
    if score is None: signal = "INSUFFICIENT_DATA"
    elif score >= 75: signal = "BUY_CANDIDATE"
    elif score >= 60: signal = "WATCH"
    elif score >= 45: signal = "HOLD / NEUTRAL"
    else: signal = "RISK / AVOID"
    return {
        "ticker": ticker,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "signal": signal,
        "score": score,
        "scores": categories,
        "metrics": snapshot,
        "methodology": "Deterministic Python scoring; missing TCBS fields are excluded, never fabricated.",
    }
