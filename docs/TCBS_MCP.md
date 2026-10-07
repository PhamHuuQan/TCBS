# TCBS MCP integration

This project keeps TDnook's original local RAG architecture and adds an adapter for the official TCBS Remote MCP Connector.

## Architecture

```
User question
   |
   +--> TDnook document RAG ------------------+
   |                                           |
   +--> finance intent + ticker                |
           |                                   |
           +--> TCBS Remote MCP (read-only) ---+--> Local LLM --> answer
```

TCBS market/fundamental data is **tool data**, not inserted into ChromaDB. This keeps live data separate from historical documents and avoids treating stale documents as current prices.

## Official endpoint

`https://mcp.tcbs.com.vn/mcp/tcinvest/`

TCBS documents OAuth 2.0 authorization and states that the connector is read-only. Never put a TCBS password or iOTP value in this repository or in `.env`.

## Current implementation

- MCP Streamable HTTP JSON-RPC client.
- MCP session preservation.
- `initialize`, `tools/list`, and `tools/call`.
- Runtime tool discovery instead of hard-coding argument schemas.
- Basic Vietnamese/English finance intent routing.
- Ticker extraction from questions.
- Live TCBS context is explicitly marked in the LLM prompt.
- If TCBS is unavailable, TDnook falls back to its existing RAG behavior; it never fabricates market data.
- `GET /tcbs/status` reports local configuration without exposing the token.
- `GET /tcbs/tools` discovers the tools currently exposed by TCBS.

## Authentication

The current adapter accepts an OAuth access token through:

```env
TCBS_MCP_ENABLED=true
TCBS_MCP_URL=https://mcp.tcbs.com.vn/mcp/tcinvest/
TCBS_MCP_ACCESS_TOKEN=...
TCBS_MCP_TIMEOUT=30
```

The token must come from an authorized OAuth flow. The application does not collect TCBS passwords or iOTP credentials.

## What is intentionally not done yet

The repository does not invent a TCBS OAuth login flow because the authorization/registration details are controlled by TCBS. The next production step is a browser-based OAuth callback that stores only the resulting token securely and refreshes it when required.

## Test

```powershell
python -m pytest tests/test_tcbs_mcp.py -q
```

## Relevant official tools

The TCBS documentation currently lists tools including:

- `getTickerOverview`
- `getStockRatio`
- `getFinancialRatioForBank`
- `getFinancialRatioForNonBank`
- `getTechnicalIndicator`
- `getVolumeAndForeign`
- `getInsiderDealing`
- `getDividendPaymentHistories`
- `getTickerActivityNews`
- `calculate_pe_ratio`
- `calculate_pb_ratio`
- current timestamp and long-term candle tools

The exact input schema is discovered from MCP at runtime so TCBS can evolve tool parameters without requiring a code rewrite.
