from __future__ import annotations

import math
from typing import Any


def _num(value: Any) -> float | None:
    if isinstance(value, bool): return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)): return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        try: return float(s.rstrip("%"))
        except ValueError: return None
    return None


def flatten(obj: Any, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            n = _num(v)
            if n is not None: out[key.lower()] = n
            else: out.update(flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj): out.update(flatten(v, f"{prefix}[{i}]"))
    return out


def find_metric(data: Any, *names: str) -> float | None:
    flat = flatten(data)
    wanted = [x.lower().replace("_", "").replace(".", "") for x in names]
    for key, value in flat.items():
        clean = key.replace("_", "").replace(".", "")
        leaf = clean.split("]")[-1]
        for w in wanted:
            if clean.endswith(w) or leaf.endswith(w): return value
    return None


def pct_score(value: float | None, low: float, high: float, higher_is_better: bool = True) -> float | None:
    if value is None: return None
    if higher_is_better:
        return max(0.0, min(100.0, (value - low) / (high - low) * 100))
    return max(0.0, min(100.0, (high - value) / (high - low) * 100))


def weighted_score(parts: dict[str, float | None]) -> float | None:
    valid = [(k, v) for k, v in parts.items() if v is not None]
    if not valid: return None
    weights = {"valuation": .25, "quality": .25, "growth": .20, "momentum": .20, "risk": .10}
    total = sum(weights.get(k, 1) * float(v) for k, v in valid)
    denom = sum(weights.get(k, 1) for k, _ in valid)
    return round(total / denom, 1)
