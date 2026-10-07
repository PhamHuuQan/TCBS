import json
import logging
import os
import re
from typing import Any

from app.tcbs.client import TCBSMCPClient, TCBSMCPError, extract_tickers

logger = logging.getLogger(__name__)

# These are official TCBS MCP tool names. The actual argument schema is discovered
# from tools/list at runtime rather than hard-coded, because TCBS can evolve it.
INTENT_TO_TOOL = [
    (r"\b(pe|p/e|pb|p/b|roe|roa|eps|bvps|định giá|valuation|định tính|chỉ số tài chính)\b", "getStockRatio"),
    (r"\b(nim|cir|npl|ldr|tăng trưởng tín dụng|ngân hàng)\b", "getFinancialRatioForBank"),
    (r"\b(bctc|báo cáo tài chính|doanh thu|lợi nhuận|ebitda|dòng tiền|cash flow|balance sheet)\b", None),
    (r"\b(rsi|macd|bollinger|ma20|ma50|ma200|kỹ thuật|technical|tín hiệu mua|tín hiệu bán)\b", "getTechnicalIndicator"),
    (r"\b(khối ngoại|foreign|nước ngoài|rs rank)\b", "getVolumeAndForeign"),
    (r"\b(cổ đông lớn|shareholder)\b", "getLargeShareHolders"),
    (r"\b(nội bộ|insider|lãnh đạo)\b", "getInsiderDealing"),
    (r"\b(cổ tức|dividend)\b", "getDividendPaymentHistories"),
    (r"\b(tin tức|news|sự kiện|đhcđ|quyền)\b", "getTickerActivityNews"),
    (r"\b(tổng quan|overview|giá hiện tại|mã cổ phiếu|ticker)\b", "getTickerOverview"),
]


def _find_tool(tools: list[dict[str, Any]], desired: str) -> dict[str, Any] | None:
    return next((t for t in tools if t.get("name") == desired), None)


def _build_arguments(tool: dict[str, Any], ticker: str) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    args: dict[str, Any] = {}
    for key in props:
        normalized = key.lower().replace("_", "")
        if normalized in {"symbol", "ticker", "stockcode", "stock", "code", "mack"}:
            args[key] = ticker
            break
    return args


def _select_intent(query: str) -> str | None:
    q = query.lower()
    for pattern, tool in INTENT_TO_TOOL:
        if re.search(pattern, q, flags=re.IGNORECASE):
            return tool
    return None


def enrich_query_with_tcbs(query: str) -> dict[str, Any] | None:
    """Fetch TCBS data for finance-like questions and return prompt-ready context.

    This is intentionally fail-closed: no token/no connection means the normal TDnook
    document RAG path remains untouched. It never fabricates market data.
    """
    if os.getenv("TCBS_MCP_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return None
    client = TCBSMCPClient()
    if not client.configured:
        return None

    tickers = extract_tickers(query)
    if not tickers:
        return None
    desired = _select_intent(query)
    if not desired:
        return None

    try:
        tools = client.list_tools()
        tool = _find_tool(tools, desired)
        if not tool:
            logger.warning("TCBS MCP tool '%s' is not currently exposed.", desired)
            return None
        ticker = tickers[0]
        args = _build_arguments(tool, ticker)
        result = client.call_tool(tool["name"], args)
        return {
            "ticker": ticker,
            "tool": tool["name"],
            "data": result,
            "source": "TCBS MCP",
        }
    except TCBSMCPError as exc:
        logger.warning("TCBS MCP unavailable: %s", exc)
        return None
    except Exception:
        logger.exception("Unexpected TCBS MCP integration error")
        return None
