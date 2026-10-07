from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import re

import httpx

from app.tcbs.client import DEFAULT_URL, TCBSMCPClient, TCBSMCPError

logger = logging.getLogger(__name__)


@dataclass
class OAuthTransaction:
    chat_id: int
    state: str
    code_verifier: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    auth_endpoint: str
    token_endpoint: str
    issuer: str
    resource: str | None
    created_at: int


class OAuthStateStore:
    """Small JSON store on Railway's durable /data volume.

    Pending OAuth state is persisted because Railway Free may sleep the service
    between the Telegram request and the browser callback.
    """

    def __init__(self) -> None:
        self.path = os.getenv("TCBS_OAUTH_STORAGE_PATH", "/data/tcbs_oauth.json")

    def _read(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                value = json.load(f)
                return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("Could not read TCBS OAuth state store")
            return {}

    def _write(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def save(self, data: dict) -> None:
        self._write(data)

    def load(self) -> dict:
        return self._read()


_store = OAuthStateStore()


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


def _load_session() -> dict:
    data = _store.load()
    session = data.get("session")
    return session if isinstance(session, dict) else {}


def _save_session(session: dict) -> None:
    data = _store.load()
    data["session"] = session
    _store.save(data)


def _clear_transaction() -> None:
    data = _store.load()
    data.pop("transaction", None)
    _store.save(data)


def access_token() -> str | None:
    session = _load_session()
    tokens = session.get("tokens") or {}
    token = str(tokens.get("access_token") or "").strip()
    return token or None


def connected() -> bool:
    token = access_token()
    if not token:
        return False
    session = _load_session()
    tokens = session.get("tokens") or {}
    expires_at = tokens.get("expires_at")
    if expires_at is not None:
        try:
            return int(expires_at) > int(time.time()) + 30
        except (TypeError, ValueError):
            pass
    return True


def disconnect() -> None:
    data = _store.load()
    data.pop("session", None)
    data.pop("transaction", None)
    _store.save(data)


def _base_origin(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _extract_www_auth_value(header: str, name: str) -> str | None:
    match = re.search(rf'{re.escape(name)}="([^"]+)"', header, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


async def _discover(server_url: str, client: httpx.AsyncClient) -> tuple[dict, dict, str]:
    response = await client.get(
        server_url,
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=False,
    )
    www = response.headers.get("WWW-Authenticate", "")
    resource_metadata_url = _extract_www_auth_value(www, "resource_metadata")

    protected = None
    candidates: list[str] = []
    if resource_metadata_url:
        candidates.append(resource_metadata_url)
    parsed = urlparse(server_url)
    candidates.extend(
        [
            f"{server_url.rstrip('/')}/.well-known/oauth-protected-resource",
            f"{_base_origin(server_url)}/.well-known/oauth-protected-resource",
        ]
    )

    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            prm = await client.get(url, follow_redirects=False)
            if prm.status_code == 200:
                body = prm.json()
                if isinstance(body, dict):
                    protected = body
                    break
        except Exception:
            continue

    if protected is None:
        if response.status_code not in {401, 403}:
            raise TCBSMCPError(
                f"TCBS OAuth discovery failed: MCP endpoint HTTP {response.status_code}"
            )
        raise TCBSMCPError(
            "TCBS không trả về Protected Resource Metadata; không thể xác định OAuth server."
        )

    authorization_servers = protected.get("authorization_servers") or []
    if not authorization_servers:
        raise TCBSMCPError("TCBS OAuth metadata không có authorization_servers.")

    issuer = str(authorization_servers[0]).rstrip("/")
    metadata_urls = [
        f"{issuer}/.well-known/oauth-authorization-server",
        f"{_base_origin(issuer)}/.well-known/oauth-authorization-server",
    ]

    oauth_metadata = None
    seen = set()
    for url in metadata_urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            meta = await client.get(url, follow_redirects=False)
            if meta.status_code == 200:
                body = meta.json()
                if isinstance(body, dict):
                    oauth_metadata = body
                    break
        except Exception:
            continue

    if oauth_metadata is None:
        raise TCBSMCPError("Không lấy được OAuth Authorization Server Metadata của TCBS.")

    return protected, oauth_metadata, issuer


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def _pick_scope(oauth_metadata: dict) -> str | None:
    configured = os.getenv("TCBS_OAUTH_SCOPE", "").strip()
    if configured:
        return configured
    supported = oauth_metadata.get("scopes_supported") or []
    if "user" in supported:
        return "user"
    return None


async def _register_client(
    oauth_metadata: dict,
    redirect: str,
    scope: str | None,
    client: httpx.AsyncClient,
) -> tuple[str, str | None, str | None]:
    endpoint = oauth_metadata.get("registration_endpoint")
    if not endpoint:
        raise TCBSMCPError(
            "TCBS OAuth không công bố registration_endpoint; flow DCR không thể tự đăng ký client."
        )

    payload = {
        "client_name": "TCBS Quant Assistant",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scope:
        payload["scope"] = scope

    response = await client.post(endpoint, json=payload)
    if response.status_code >= 400:
        detail = response.text[:800]
        raise TCBSMCPError(
            f"TCBS Dynamic Client Registration HTTP {response.status_code}: {detail}"
        )

    body = response.json()
    client_id = str(body.get("client_id") or "").strip()
    if not client_id:
        raise TCBSMCPError("TCBS DCR không trả về client_id.")
    client_secret = body.get("client_secret")
    token_auth = body.get("token_endpoint_auth_method")
    return client_id, client_secret, token_auth


async def _prepare_authorization(chat_id: int) -> str:
    redirect = public_redirect_uri()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        protected, oauth, issuer = await _discover(DEFAULT_URL, client)

        scope = _pick_scope(oauth)
        client_id, client_secret, token_auth = await _register_client(
            oauth, redirect, scope, client
        )

        # TCBS MCP is a public resource; keep resource URL canonical (no trailing slash)
        # to avoid RFC 8707 mismatches across authorization servers.
        resource = str(
            protected.get("resource")
            or DEFAULT_URL.rstrip("/")
        ).strip()

        auth_endpoint = str(oauth.get("authorization_endpoint") or "").strip()
        token_endpoint = str(oauth.get("token_endpoint") or "").strip()
        if not auth_endpoint or not token_endpoint:
            raise TCBSMCPError(
                "TCBS OAuth metadata thiếu authorization_endpoint hoặc token_endpoint."
            )

        if token_auth not in (None, "none", "client_secret_post", "client_secret_basic"):
            raise TCBSMCPError(
                f"TCBS trả về token_endpoint_auth_method không hỗ trợ: {token_auth}"
            )

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(32)

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if resource:
            params["resource"] = resource
        if scope:
            params["scope"] = scope

        transaction = {
            "chat_id": chat_id,
            "state": state,
            "code_verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "auth_endpoint": auth_endpoint,
            "token_endpoint": token_endpoint,
            "issuer": issuer,
            "resource": resource,
            "created_at": int(time.time()),
        }
        data = _store.load()
        # Only one active transaction per Telegram chat.
        data["transaction"] = transaction
        _store.save(data)

        return f"{auth_endpoint}?{urlencode(params)}"


async def start_telegram_oauth(
    chat_id: int,
    on_url: Callable[[str], Awaitable[None]],
) -> None:
    if connected():
        await on_url(public_redirect_uri() + "?tcbs=connected")
        return
    url = await _prepare_authorization(chat_id)
    await on_url(url)


async def _exchange_code(
    transaction: dict,
    code: str,
    callback_iss: str | None,
) -> str:
    expected_issuer = str(transaction.get("issuer") or "").rstrip("/")
    if callback_iss and str(callback_iss).rstrip("/") != expected_issuer:
        raise TCBSMCPError("OAuth issuer (iss) không khớp máy chủ TCBS đã phát hiện.")

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": transaction["redirect_uri"],
        "client_id": transaction["client_id"],
        "code_verifier": transaction["code_verifier"],
    }
    resource = transaction.get("resource")
    if resource:
        form["resource"] = str(resource)

    secret = transaction.get("client_secret")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if secret:
        auth_method = transaction.get("token_endpoint_auth_method")
        if auth_method == "client_secret_basic":
            raw = f"{transaction['client_id']}:{secret}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        else:
            form["client_secret"] = str(secret)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        response = await client.post(transaction["token_endpoint"], data=form, headers=headers)

    if response.status_code >= 400:
        raise TCBSMCPError(
            f"TCBS token exchange HTTP {response.status_code}: {response.text[:900]}"
        )

    body = response.json()
    token = str(body.get("access_token") or "").strip()
    if not token:
        raise TCBSMCPError("TCBS token endpoint không trả về access_token.")

    expires_in = body.get("expires_in")
    try:
        expires_at = int(time.time()) + int(expires_in) if expires_in else None
    except (TypeError, ValueError):
        expires_at = None

    data = _store.load()
    data["session"] = {
        "client_id": transaction["client_id"],
        "client_secret": transaction.get("client_secret"),
        "issuer": transaction.get("issuer"),
        "redirect_uri": transaction.get("redirect_uri"),
        "resource": transaction.get("resource"),
        "tokens": {
            "access_token": token,
            "refresh_token": body.get("refresh_token"),
            "token_type": body.get("token_type", "Bearer"),
            "scope": body.get("scope"),
            "expires_at": expires_at,
        },
        "connected_at": int(time.time()),
    }
    data.pop("transaction", None)
    _store.save(data)

    # Verify immediately against the official TCBS MCP after OAuth.
    try:
        verifier = TCBSMCPClient(access_token=token)
        verifier.list_tools()
    except Exception as exc:
        # Keep the token stored; the caller gets the real verification reason.
        raise TCBSMCPError(f"OAuth thành công nhưng kiểm tra TCBS MCP thất bại: {exc}") from exc

    return token


async def receive_callback(
    code: str | None,
    state: str | None,
    iss: str | None,
    error: str | None = None,
    error_description: str | None = None,
) -> int | None:
    if error:
        raise TCBSMCPError(
            f"TCBS OAuth bị từ chối: {error}"
            + (f" — {error_description}" if error_description else "")
        )
    if not code or not state:
        raise TCBSMCPError("OAuth callback thiếu code hoặc state.")

    data = _store.load()
    transaction = data.get("transaction")
    if not isinstance(transaction, dict):
        raise TCBSMCPError(
            "Không còn phiên OAuth đang chờ. Hãy bấm /tcbs để tạo phiên mới."
        )

    created_at = int(transaction.get("created_at") or 0)
    if created_at and int(time.time()) - created_at > 600:
        _clear_transaction()
        raise TCBSMCPError("Phiên OAuth đã hết hạn. Hãy bấm /tcbs để thử lại.")

    expected_state = str(transaction.get("state") or "")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise TCBSMCPError("OAuth state không khớp.")

    await _exchange_code(transaction, code, iss)
    return int(transaction["chat_id"])


async def connect_and_list_tools() -> list[dict]:
    """Compatibility endpoint: starts a browser OAuth flow but cannot map a Telegram chat.

    The Telegram path is the supported production flow. This function is retained for
    the web API and logs the authorization URL for manual use.
    """
    if connected():
        client = TCBSMCPClient()
        return client.list_tools()

    raise TCBSMCPError(
        "Hãy dùng /tcbs trên Telegram để bắt đầu OAuth TCBS và nhận link xác thực."
    )


def callback_from_url(url: str) -> tuple[str, str | None, str | None]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [None])[0]
    iss = params.get("iss", [None])[0]
    if not code:
        raise ValueError("OAuth callback không chứa authorization code.")
    return code, state, iss
