from __future__ import annotations

import asyncio
import os
import webbrowser
from urllib.parse import parse_qs, urlparse

from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, OAuthClientMetadata
import httpx2
from pydantic import AnyUrl

from app.tcbs.client import DEFAULT_URL

class InMemoryTokenStorage(TokenStorage):
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info

_storage = InMemoryTokenStorage()
_callback_future: asyncio.Future[AuthorizationCodeResult] | None = None
_lock = asyncio.Lock()

def redirect_uri() -> str:
    return os.getenv("TCBS_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/tcbs/oauth/callback").strip()

def access_token() -> str | None:
    token = _storage.tokens
    return (getattr(token, "access_token", None) or None) if token else None

def connected() -> bool:
    return bool(access_token())

def disconnect() -> None:
    _storage.tokens = None
    _storage.client_info = None

async def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass

async def _wait_for_callback() -> AuthorizationCodeResult:
    global _callback_future
    loop = asyncio.get_running_loop()
    _callback_future = loop.create_future()
    try:
        return await asyncio.wait_for(_callback_future, timeout=300)
    finally:
        _callback_future = None

def receive_callback(code: str, state: str | None, iss: str | None) -> bool:
    future = _callback_future
    if future is None or future.done():
        return False
    future.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss))
    return True

async def connect_and_list_tools() -> list[dict]:
    async with _lock:
        metadata = OAuthClientMetadata(
            client_name="TDnook TCBS Quant Assistant",
            redirect_uris=[AnyUrl(redirect_uri())],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        )
        provider = OAuthClientProvider(
            server_url=DEFAULT_URL,
            client_metadata=metadata,
            storage=_storage,
            redirect_handler=_open_browser,
            callback_handler=_wait_for_callback,
        )
        async with httpx2.AsyncClient(auth=provider, timeout=60.0) as http_client:
            transport = streamable_http_client(DEFAULT_URL, http_client=http_client)
            async with Client(transport) as client:
                result = await client.list_tools()
                return [{"name": tool.name, "description": getattr(tool, "description", None), "inputSchema": getattr(tool, "inputSchema", None)} for tool in result.tools]

def callback_from_url(url: str) -> tuple[str, str | None, str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [None])[0]
    iss = params.get("iss", [None])[0]
    if not code:
        raise ValueError("OAuth callback không chứa authorization code.")
    return code, state, iss
