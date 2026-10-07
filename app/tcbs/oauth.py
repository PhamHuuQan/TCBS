from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx2
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from app.tcbs.client import DEFAULT_URL

logger = logging.getLogger(__name__)


class InMemoryTokenStorage(TokenStorage):
    """Persistent OAuth client/token storage on the Railway volume."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None
        self.path = os.getenv("TCBS_OAUTH_STORAGE_PATH", "/data/tcbs_oauth.json")

    async def _load(self) -> None:
        if self.tokens is not None or self.client_info is not None:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("tokens"):
                self.tokens = OAuthToken.model_validate(data["tokens"])
            if data.get("client_info"):
                self.client_info = OAuthClientInformationFull.model_validate(data["client_info"])
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("Could not load persisted TCBS OAuth state")
            self.tokens = None
            self.client_info = None

    async def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        data = {
            "tokens": self.tokens.model_dump(mode="json") if self.tokens else None,
            "client_info": self.client_info.model_dump(mode="json") if self.client_info else None,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    async def get_tokens(self) -> OAuthToken | None:
        await self._load()
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        await self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        await self._load()
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info
        await self._save()


_storage = InMemoryTokenStorage()
_lock = asyncio.Lock()
_pending: dict[int, _PendingOAuth] = {}
_pending_by_state: dict[str, _PendingOAuth] = {}


def public_redirect_uri() -> str:
    explicit = os.getenv("TCBS_OAUTH_REDIRECT_URI", "").strip()
    if explicit:
        return explicit.rstrip("/")
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}/tcbs/oauth/callback"
    return "http://127.0.0.1:8000/tcbs/oauth/callback"


def redirect_uri() -> str:
    return public_redirect_uri()


def access_token() -> str | None:
    token = _storage.tokens
    return getattr(token, "access_token", None) if token else None


def connected() -> bool:
    return bool(access_token())


def disconnect() -> None:
    _storage.tokens = None
    _storage.client_info = None


def _metadata() -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="TCBS Quant Assistant",
        redirect_uris=[AnyUrl(public_redirect_uri())],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


async def _callback_for_pending(pending: _PendingOAuth) -> AuthorizationCodeResult:
    try:
        return await asyncio.wait_for(pending.future, timeout=300)
    finally:
        if pending.state:
            _pending_by_state.pop(pending.state, None)
        _pending.pop(pending.chat_id, None)


async def start_telegram_oauth(
    chat_id: int,
    on_url: Callable[[str], Awaitable[None]],
) -> None:
    if connected():
        await on_url(public_redirect_uri() + "?tcbs=connected")
        return
    async with _lock:
        existing = _pending.get(chat_id)
        if existing:
            raise RuntimeError("Một phiên kết nối TCBS của tài khoản này đang chờ xác thực.")
        loop = asyncio.get_running_loop()
        pending = _PendingOAuth(chat_id=chat_id, future=loop.create_future(), on_url=on_url)
        _pending[chat_id] = pending
        asyncio.create_task(_run_oauth(pending))


async def _run_oauth(pending: _PendingOAuth) -> None:
    async def redirect_handler(url: str) -> None:
        params = parse_qs(urlparse(url).query)
        pending.state = params.get("state", [None])[0]
        if pending.state:
            _pending_by_state[pending.state] = pending
        if pending.on_url:
            await pending.on_url(url)

    async def callback_handler() -> AuthorizationCodeResult:
        return await _callback_for_pending(pending)

    try:
        provider = OAuthClientProvider(
            server_url=DEFAULT_URL,
            client_metadata=_metadata(),
            storage=_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        async with httpx2.AsyncClient(
            auth=provider,
            timeout=httpx2.Timeout(60.0, read=300.0),
        ) as http_client:
            transport = streamable_http_client(DEFAULT_URL, http_client=http_client)
            async with Client(transport) as client:
                await client.list_tools()
        logger.info("TCBS OAuth connected for Telegram chat %s", pending.chat_id)
        if pending.on_url:
            await pending.on_url(public_redirect_uri() + "?tcbs=connected")
    except Exception as exc:
        logger.exception("TCBS OAuth failed for Telegram chat %s: %s", pending.chat_id, exc)
        if pending.on_url:
            safe = str(exc).replace("\n", " ")[:240]
            await pending.on_url(public_redirect_uri() + f"?tcbs=error&message={safe}")
    finally:
        if pending.state:
            _pending_by_state.pop(pending.state, None)
        _pending.pop(pending.chat_id, None)


async def connect_and_list_tools() -> list[dict]:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[AuthorizationCodeResult] = loop.create_future()
    local_pending = _PendingOAuth(chat_id=-1, future=future)

    async def redirect_handler(url: str) -> None:
        local_pending.state = parse_qs(urlparse(url).query).get("state", [None])[0]
        logger.warning("TCBS OAuth authorization URL: %s", url)
        print("TCBS OAuth authorization URL:", url, flush=True)

    async def callback_handler() -> AuthorizationCodeResult:
        return await asyncio.wait_for(future, timeout=300)

    provider = OAuthClientProvider(
        server_url=DEFAULT_URL,
        client_metadata=_metadata(),
        storage=_storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    async with httpx2.AsyncClient(
        auth=provider,
        timeout=httpx2.Timeout(60.0, read=300.0),
    ) as http_client:
        transport = streamable_http_client(DEFAULT_URL, http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": getattr(tool, "description", None),
                    "inputSchema": getattr(tool, "inputSchema", None),
                }
                for tool in result.tools
            ]


def receive_callback(code: str, state: str | None, iss: str | None) -> bool:
    if not code:
        return False
    pending = _pending_by_state.get(state or "")
    if not pending or pending.future.done():
        return False
    pending.future.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss))
    return True


def callback_from_url(url: str) -> tuple[str, str | None, str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [None])[0]
    iss = params.get("iss", [None])[0]
    if not code:
        raise ValueError("OAuth callback không chứa authorization code.")
    return code, state, iss
