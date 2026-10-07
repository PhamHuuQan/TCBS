from __future__ import annotations

import logging
from typing import Any

from app.tcbs.client import TCBSMCPClient, TCBSMCPError

logger = logging.getLogger(__name__)


def _tool_map(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(t.get("name")): t for t in tools if t.get("name")}


def _arguments(tool: dict[str, Any], ticker: str) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    args: dict[str, Any] = {}
    for key in props:
        normalized = key.lower().replace("_", "")
        if normalized in {"symbol", "ticker", "stockcode", "stock", "code", "mack", "tickersymbol"}:
            args[key] = ticker
            break
    return args


def collect_tcbs_snapshot(ticker: str) -> dict[str, Any]:
    """Collect several read-only TCBS MCP tool results for one ticker.

    Tool names are matched from the live tools/list response. Any unavailable tool is
    skipped, so the quant engine can still operate on partial data without inventing it.
    """
    client = TCBSMCPClient()
    if not client.configured:
        raise TCBSMCPError("TCBS MCP chưa được kết nối. Hãy kết nối TCBS trước.")
    tools = _tool_map(client.list_tools())
    preferred = [
        "getTickerOverview", "getStockRatio", "getFinancialRatioForBank",
        "getFinancialRatioForNonBank", "getTechnicalIndicator", "getVolumeAndForeign",
        "getLargeShareHolders", "getInsiderDealing", "getDividendPaymentHistories",
        "getTickerActivityNews",
    ]
    snapshot: dict[str, Any] = {}
    for name in preferred:
        tool = tools.get(name)
        if not tool: continue
        try:
            snapshot[name] = client.call_tool(name, _arguments(tool, ticker))
        except Exception as exc:
            logger.info("Skipping TCBS tool %s for %s: %s", name, ticker, exc)
    return snapshot
