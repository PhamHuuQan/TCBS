import json
import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://mcp.tcbs.com.vn/mcp/tcinvest/"


class TCBSMCPError(RuntimeError):
    """Raised when the TCBS MCP endpoint cannot complete an operation."""


class TCBSMCPClient:
    """Small dependency-light MCP Streamable HTTP client for the official TCBS endpoint.

    Authentication is deliberately token-based. The application never stores TCBS
    passwords or iOTP credentials. OAuth login/consent remains an external step;
    the resulting access token can be supplied through TCBS_MCP_ACCESS_TOKEN.
    """

    def __init__(self, url: str | None = None, access_token: str | None = None, timeout: int | None = None):
        self.url = (url or os.getenv("TCBS_MCP_URL", DEFAULT_URL)).strip()
        self.access_token = (access_token or os.getenv("TCBS_MCP_ACCESS_TOKEN", "")).strip()
        self.timeout = int(timeout or os.getenv("TCBS_MCP_TIMEOUT", "30"))
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        })
        if self.access_token:
            self.session.headers["Authorization"] = f"Bearer {self.access_token}"
        self._session_id: str | None = None
        self._request_id = 0

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        events: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                current.append(line[5:].lstrip())
            elif line.strip() == "" and current:
                events.append("\n".join(current))
                current = []
        if current:
            events.append("\n".join(current))
        for event in reversed(events):
            if not event or event == "[DONE]":
                continue
            try:
                payload = json.loads(event)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                continue
        raise TCBSMCPError("TCBS MCP trả về SSE nhưng không có JSON-RPC event hợp lệ.")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self.session.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if response.status_code in (401, 403):
            raise TCBSMCPError("TCBS MCP yêu cầu xác thực OAuth hoặc access token đã hết hạn.")
        if not response.ok:
            detail = response.text[:1000]
            raise TCBSMCPError(f"TCBS MCP HTTP {response.status_code}: {detail}")

        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text)
        try:
            data = response.json()
        except ValueError as exc:
            raise TCBSMCPError("TCBS MCP trả về dữ liệu không phải JSON/JSON-RPC.") from exc
        if not isinstance(data, dict):
            raise TCBSMCPError("TCBS MCP response không hợp lệ.")
        return data

    def initialize(self) -> dict[str, Any]:
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": os.getenv("TCBS_MCP_PROTOCOL_VERSION", "2025-06-18"),
                "capabilities": {},
                "clientInfo": {"name": "TCBS-TDnook", "version": "0.1.0"},
            },
        })
        if "error" in result:
            raise TCBSMCPError(str(result["error"]))
        # MCP requires initialized notification before normal operations.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return result.get("result", {})

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        })
        if "error" in result:
            raise TCBSMCPError(str(result["error"]))
        return result.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        if "error" in result:
            raise TCBSMCPError(str(result["error"]))
        return result.get("result", {})


def extract_tickers(text: str) -> list[str]:
    # Vietnamese listed-company tickers are normally 3-4 uppercase letters.
    candidates = re.findall(r"(?<![A-Za-z0-9])([A-Z]{3,4})(?![A-Za-z0-9])", text or "")
    stop = {"PE", "PB", "ROE", "ROA", "EPS", "NIM", "MACD", "RSI", "BCTC", "TCBS", "MCP"}
    return list(dict.fromkeys(x for x in candidates if x not in stop))
