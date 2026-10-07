
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import hashlib
from pathlib import Path
from typing import Any

import httpx

from app.quant.analyzer import analyze_ticker
from app.quant.compare import compare_tickers
from app.quant.screener import screen_tickers
from app.rag.pipeline import ingest_document
from app.rag.retriever import retrieve_top_k
from app.tcbs.client import TCBSMCPClient, extract_tickers
from app.tcbs.router import enrich_query_with_tcbs
from app.telegram.ai import CloudAIError, ask_gemini, synthesize_quant
from app.telegram.keyboards import alerts_menu, after_ticker, main_menu, watch_menu
from app.telegram.storage import (
    active_alerts,
    add_alert,
    add_watch,
    allowed_user,
    disable_alert,
    get_pending_action,
    init_db,
    list_alerts,
    list_watch,
    recent_history,
    remove_watch,
    save_history,
    set_pending_action,
    trigger_alert,
    update_alert_price,
    upsert_user,
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MAX_DOWNLOAD_BYTES = int(os.getenv("TELEGRAM_MAX_DOWNLOAD_MB", "20")) * 1024 * 1024
_tasks: set[asyncio.Task] = set()


def _token() -> str:
    token = (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_TOKEN", "").strip()
    )
    if not token:
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN.")
    return token


def telegram_webhook_secret() -> str:
    explicit = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if explicit:
        return explicit
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return "telegram-webhook-not-configured"
    return "tcbs-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _webhook_url() -> str | None:
    explicit = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        secret = telegram_webhook_secret()
        return f"https://{domain}/telegram/webhook/{secret}"
    return None


async def telegram_call(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload or {})
        data = response.json()
        if response.status_code >= 400 or not data.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed: {response.status_code} {data}")
        return data


async def send_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> None:
    text = text or "Không có dữ liệu."
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if idx == len(chunks) - 1 and reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await telegram_call("sendMessage", payload)
        except Exception:
            if parse_mode:
                payload.pop("parse_mode", None)
                await telegram_call("sendMessage", payload)
            else:
                raise


async def answer_callback(callback_id: str) -> None:
    try:
        await telegram_call("answerCallbackQuery", {"callback_query_id": callback_id})
    except Exception:
        pass


def _ok_update_user(message: dict[str, Any]) -> bool:
    user = message.get("from") or {}
    chat = message.get("chat") or {}
    return allowed_user(int(chat.get("id", 0)), int(user.get("id", 0)))


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return html.escape(str(v))


def _signal(s: str) -> str:
    return {
        "BUY_CANDIDATE": "🟢 BUY CANDIDATE",
        "WATCH": "🟡 WATCH",
        "HOLD / NEUTRAL": "⚪ HOLD / NEUTRAL",
        "RISK / AVOID": "🔴 RISK / AVOID",
        "INSUFFICIENT_DATA": "⚠️ INSUFFICIENT DATA",
    }.get(s, html.escape(s))


def _format_quant(result: dict[str, Any]) -> str:
    scores = result.get("scores") or {}
    lines = [
        f"<b>{html.escape(result.get('ticker',''))}</b> — {_signal(result.get('signal',''))}",
        f"<b>Quant score:</b> {_fmt(result.get('score'))}/100",
        "",
        f"Định giá: {_fmt(scores.get('valuation'))}",
        f"Chất lượng: {_fmt(scores.get('quality'))}",
        f"Tăng trưởng: {_fmt(scores.get('growth'))}",
        f"Momentum: {_fmt(scores.get('momentum'))}",
        f"Rủi ro: {_fmt(scores.get('risk'))}",
        "",
        f"<i>Nguồn tính điểm:</i> TCBS MCP + deterministic Python.",
    ]
    return "\n".join(lines)


def _flatten_numeric(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten_numeric(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            out.extend(_flatten_numeric(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append((prefix, obj))
    return out


async def _safe_quant(ticker: str) -> dict[str, Any]:
    return await asyncio.to_thread(analyze_ticker, ticker)


async def _send_quant(chat_id: int, ticker: str) -> None:
    result = await _safe_quant(ticker)
    text = _format_quant(result)
    try:
        explanation = await synthesize_quant(result)
        text += "\n\n<b>AI diễn giải</b>\n" + html.escape(explanation)
    except Exception as exc:
        logger.warning("Quant AI synthesis failed: %s", exc)
    await send_message(chat_id, text, after_ticker(ticker))


async def _send_compare(chat_id: int, tickers: list[str]) -> None:
    result = await asyncio.to_thread(compare_tickers, tickers)
    rows = result.get("analyses", result.get("results", result if isinstance(result, list) else []))
    lines = ["<b>SO SÁNH QUANT</b>", ""]
    for item in rows:
        lines.append(
            f"<b>{html.escape(item.get('ticker',''))}</b>  "
            f"{_fmt(item.get('score'))}/100  {_signal(item.get('signal',''))}"
        )
    await send_message(chat_id, "\n".join(lines), main_menu())


async def _send_screen(chat_id: int, tickers: list[str]) -> None:
    result = await asyncio.to_thread(screen_tickers, tickers)
    rows = result.get("results", result if isinstance(result, list) else [])
    lines = ["<b>SCREENER QUANT</b>", ""]
    for i, item in enumerate(rows, 1):
        lines.append(
            f"{i}. <b>{html.escape(item.get('ticker',''))}</b> — "
            f"{_fmt(item.get('score'))}/100 — {_signal(item.get('signal',''))}"
        )
    await send_message(chat_id, "\n".join(lines), main_menu())


async def _send_tool(chat_id: int, query: str, title: str) -> None:
    ctx = await asyncio.to_thread(enrich_query_with_tcbs, query)
    if not ctx:
        await send_message(
            chat_id,
            "⚠️ Không lấy được dữ liệu TCBS. Hãy kiểm tra kết nối TCBS MCP.",
            main_menu(),
        )
        return
    raw = ctx.get("data")
    lines = [f"<b>{html.escape(title)}</b>", f"Mã: <b>{html.escape(ctx.get('ticker',''))}</b>", ""]
    nums = _flatten_numeric(raw)
    if nums:
        for key, value in nums[:25]:
            lines.append(f"<code>{html.escape(key)}</code>: <b>{_fmt(value)}</b>")
    else:
        lines.append("<pre>" + html.escape(json.dumps(raw, ensure_ascii=False, default=str)[:3200]) + "</pre>")
    await send_message(chat_id, "\n".join(lines), after_ticker(ctx.get("ticker", "")))


async def _send_watchlist(chat_id: int) -> None:
    items = list_watch(chat_id)
    if not items:
        await send_message(chat_id, "⭐ Watchlist đang trống.", watch_menu())
        return
    results = []
    for ticker in items[:20]:
        try:
            results.append(await _safe_quant(ticker))
        except Exception as exc:
            results.append({"ticker": ticker, "score": None, "signal": str(exc)})
    lines = ["<b>⭐ WATCHLIST</b>", ""]
    for x in results:
        lines.append(
            f"<b>{html.escape(x.get('ticker',''))}</b>: "
            f"{_fmt(x.get('score'))}/100 — {_signal(x.get('signal',''))}"
        )
    await send_message(chat_id, "\n".join(lines), watch_menu())


def _price_from_tcbs(raw: Any) -> float | None:
    preferred = {"price", "lastprice", "currentprice", "close", "closingprice", "matchedprice", "referenceprice"}
    for key, value in _flatten_numeric(raw):
        leaf = key.split(".")[-1].replace("_", "").lower()
        if leaf in preferred and isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return None


async def _alert_worker() -> None:
    while True:
        try:
            for alert in active_alerts():
                try:
                    ctx = await asyncio.to_thread(
                        enrich_query_with_tcbs,
                        f"giá hiện tại {alert['ticker']}",
                    )
                    if not ctx:
                        continue
                    price = _price_from_tcbs(ctx.get("data"))
                    if price is None:
                        continue
                    update_alert_price(alert["id"], price)
                    hit = (
                        alert["direction"] == "above" and price >= alert["target"]
                    ) or (
                        alert["direction"] == "below" and price <= alert["target"]
                    )
                    if hit:
                        await send_message(
                            int(alert["chat_id"]),
                            f"🚨 <b>CẢNH BÁO GIÁ</b>\n"
                            f"{html.escape(alert['ticker'])}: {_fmt(price)}\n"
                            f"Điều kiện: {html.escape(alert['direction'])} {_fmt(alert['target'])}",
                            alerts_menu(),
                        )
                        trigger_alert(alert["id"])
                except Exception as exc:
                    logger.warning("Alert %s failed: %s", alert["id"], exc)
        except Exception:
            logger.exception("Alert worker cycle failed")
        await asyncio.sleep(int(os.getenv("TELEGRAM_ALERT_POLL_SECONDS", "300")))


async def telegram_startup() -> None:
    init_db()
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        logger.warning("Telegram bot disabled: TELEGRAM_BOT_TOKEN is missing.")
        return
    url = _webhook_url()
    if not url:
        logger.warning("Telegram webhook not configured: set TELEGRAM_WEBHOOK_URL or generate Railway domain.")
        return
    try:
        await telegram_call(
            "setWebhook",
            {
                "url": url,
                "secret_token": telegram_webhook_secret(),
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
        )
        me = await telegram_call("getMe")
        logger.info("Telegram webhook ready for @%s -> %s", me.get("result", {}).get("username"), url)
    except Exception:
        logger.exception("Could not configure Telegram webhook")
        return
    task = asyncio.create_task(_alert_worker())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def telegram_shutdown() -> None:
    for task in list(_tasks):
        task.cancel()
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def _handle_command(message: dict[str, Any], text: str) -> None:
    chat_id = int(message["chat"]["id"])
    parts = text.strip().split()
    cmd = parts[0].split("@")[0].lower()

    if cmd in {"/start", "/menu"}:
        await send_message(
            chat_id,
            "<b>TCBS Quant Assistant</b>\n\n"
            "Telegram là giao diện chính: TCBS MCP + Quant Engine + BCTC/RAG + AI API.",
            main_menu(),
        )
        return

    if cmd == "/id":
        await send_message(
            chat_id,
            f"Telegram user ID của bạn: <code>{message.get('from',{}).get('id')}</code>\n"
            "Dùng ID này trong TELEGRAM_ALLOWED_USER_IDS trên Railway.",
        )
        return

    if cmd in {"/help", "/about"}:
        await send_message(
            chat_id,
            "<b>Trợ lý có thể làm</b>\n"
            "/analyze VCB\n/compare VCB BID CTG MBB\n"
            "/screen VCB BID CTG MBB TCB VPB ACB\n"
            "/watch list | /watch add VCB | /watch del VCB\n"
            "/alert VCB above 100 | /alert VCB below 90\n"
            "/ai nội dung cần hỏi\n"
            "/tcbs\n/id\n/menu",
            main_menu(),
        )
        return

    if cmd == "/analyze":
        if len(parts) < 2:
            set_pending_action(chat_id, "analyze")
            await send_message(chat_id, "Gửi mã cổ phiếu, ví dụ <code>VCB</code>.")
            return
        await _send_quant(chat_id, parts[1].upper())
        return

    if cmd == "/compare":
        tickers = [x.upper() for x in parts[1:] if re.fullmatch(r"[A-Za-z]{3,4}", x)]
        if len(tickers) < 2:
            set_pending_action(chat_id, "compare")
            await send_message(chat_id, "Gửi các mã, ví dụ <code>VCB BID CTG MBB</code>.")
            return
        await _send_compare(chat_id, tickers[:20])
        return

    if cmd == "/screen":
        tickers = [x.upper() for x in parts[1:] if re.fullmatch(r"[A-Za-z]{3,4}", x)]
        if not tickers:
            set_pending_action(chat_id, "screen")
            await send_message(chat_id, "Gửi universe cần lọc, tối đa 50 mã.")
            return
        await _send_screen(chat_id, tickers[:50])
        return

    if cmd == "/watch":
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub == "list":
            await _send_watchlist(chat_id)
        elif sub == "add" and len(parts) > 2:
            add_watch(chat_id, parts[2].upper())
            await _send_watchlist(chat_id)
        elif sub == "del" and len(parts) > 2:
            remove_watch(chat_id, parts[2].upper())
            await _send_watchlist(chat_id)
        else:
            await send_message(chat_id, "Cú pháp: <code>/watch add VCB</code>", watch_menu())
        return

    if cmd == "/alert":
        if len(parts) >= 4 and parts[2].lower() in {"above", "below"}:
            try:
                alert_id = add_alert(chat_id, parts[1].upper(), parts[2].lower(), float(parts[3]))
                await send_message(chat_id, f"✅ Đã tạo cảnh báo #{alert_id}.", alerts_menu())
            except ValueError:
                await send_message(chat_id, "Giá mục tiêu phải là số.", alerts_menu())
        else:
            await send_message(
                chat_id,
                "Cú pháp: <code>/alert VCB above 100</code> hoặc <code>/alert VCB below 90</code>",
                alerts_menu(),
            )
        return

    if cmd == "/alerts":
        rows = list_alerts(chat_id)
        if not rows:
            await send_message(chat_id, "🚨 Chưa có cảnh báo.", alerts_menu())
            return
        lines = ["<b>🚨 CẢNH BÁO</b>", ""]
        for x in rows:
            state = "🟢" if x["enabled"] else "⚪"
            lines.append(
                f"{state} #{x['id']} {html.escape(x['ticker'])} "
                f"{html.escape(x['direction'])} {_fmt(x['target'])} | last={_fmt(x['last_price'])}"
            )
        await send_message(chat_id, "\n".join(lines), alerts_menu())
        return

    if cmd == "/ai":
        question = text.partition(" ")[2].strip()
        if not question:
            set_pending_action(chat_id, "ai")
            await send_message(chat_id, "Gửi câu hỏi cho AI.")
            return
        await _ask_ai(chat_id, question)
        return

    if cmd == "/tcbs":
        await _start_tcbs(chat_id)
        return

    await _ask_ai(chat_id, text)


async def _ask_ai(chat_id: int, question: str) -> None:
    history = recent_history(chat_id)
    ticker_context = await asyncio.to_thread(enrich_query_with_tcbs, question)
    doc_chunks = []
    try:
        doc_chunks = await asyncio.to_thread(retrieve_top_k, question)
    except Exception as exc:
        logger.warning("RAG retrieval skipped: %s", exc)

    parts = []
    if ticker_context:
        parts.append("TCBS MCP:\n" + json.dumps(ticker_context, ensure_ascii=False, default=str)[:7000])
    if doc_chunks:
        sources = []
        for c in doc_chunks[:6]:
            meta = c.get("metadata", {})
            sources.append(
                f"[{meta.get('filename','Tài liệu')} trang {meta.get('page', meta.get('page_num','?'))}]\n"
                f"{c.get('text','')[:1800]}"
            )
        parts.append("BCTC/RAG:\n" + "\n\n".join(sources))

    try:
        answer = await ask_gemini(question, "\n\n".join(parts), history)
    except CloudAIError as exc:
        answer = f"⚠️ {exc}"
    save_history(chat_id, "user", question)
    save_history(chat_id, "assistant", answer)
    await send_message(chat_id, html.escape(answer), main_menu())


async def _start_tcbs(chat_id: int) -> None:
    from app.tcbs.oauth import start_telegram_oauth

    async def notify(url: str) -> None:
        if "tcbs=connected" in url:
            await send_message(chat_id, "✅ <b>TCBS đã kết nối.</b> Bạn có thể dùng toàn bộ menu dữ liệu/quant.", main_menu())
        elif "tcbs=error" in url:
            await send_message(chat_id, "❌ <b>OAuth TCBS thất bại.</b> Hãy thử Kết nối TCBS lại.", main_menu())
        else:
            await send_message(
                chat_id,
                "🔐 <b>Kết nối TCBS</b>\n\n"
                "Mở link dưới đây, đăng nhập TCBS và xác nhận iOTP. "
                "Sau khi xác thực xong trang sẽ quay về Railway.\n\n"
                f"<a href=\"{html.escape(url)}\">MỞ TRANG XÁC THỰC TCBS</a>",
            )

    try:
        await start_telegram_oauth(chat_id, notify)
    except Exception as exc:
        await send_message(chat_id, f"⚠️ Không khởi động được OAuth TCBS: {html.escape(str(exc))}", main_menu())


async def _handle_action(chat_id: int, action: str, text: str) -> None:
    clean = text.strip()
    tickers = extract_tickers(clean)

    if action in {"analyze", "technical", "valuation", "bank", "news", "foreign", "owners", "dividend"}:
        if not tickers:
            await send_message(chat_id, "Hãy gửi mã cổ phiếu, ví dụ <code>VCB</code>.")
            return
        ticker = tickers[0]
        if action == "analyze":
            await _send_quant(chat_id, ticker)
        else:
            query_map = {
                "technical": f"phân tích kỹ thuật {ticker} RSI MACD MA",
                "valuation": f"định giá {ticker} PE PB ROE EPS",
                "bank": f"{ticker} NIM CIR NPL LDR ngân hàng",
                "news": f"tin tức sự kiện {ticker}",
                "foreign": f"khối ngoại {ticker}",
                "owners": f"cổ đông lớn insider {ticker}",
                "dividend": f"cổ tức {ticker}",
            }
            title_map = {
                "technical": "📈 PHÂN TÍCH KỸ THUẬT",
                "valuation": "💰 ĐỊNH GIÁ / CHỈ SỐ",
                "bank": "🏦 CHỈ SỐ NGÂN HÀNG",
                "news": "📰 TIN TỨC / SỰ KIỆN",
                "foreign": "🌍 KHỐI NGOẠI",
                "owners": "👤 CỔ ĐÔNG / INSIDER",
                "dividend": "💵 CỔ TỨC",
            }
            await _send_tool(chat_id, query_map[action], title_map[action])
        set_pending_action(chat_id, None)
        return

    if action in {"compare", "screen"}:
        if len(tickers) < 2:
            await send_message(chat_id, "Hãy gửi ít nhất 2 mã, ví dụ <code>VCB BID CTG MBB</code>.")
            return
        if action == "compare":
            await _send_compare(chat_id, tickers[:20])
        else:
            await _send_screen(chat_id, tickers[:50])
        set_pending_action(chat_id, None)
        return

    if action == "ai":
        await _ask_ai(chat_id, clean)
        set_pending_action(chat_id, None)
        return

    if action == "watch_add":
        if not tickers:
            await send_message(chat_id, "Gửi mã cần thêm, ví dụ <code>VCB</code>.")
            return
        add_watch(chat_id, tickers[0])
        set_pending_action(chat_id, None)
        await _send_watchlist(chat_id)
        return

    if action == "watch_del":
        if not tickers:
            await send_message(chat_id, "Gửi mã cần xóa, ví dụ <code>VCB</code>.")
            return
        remove_watch(chat_id, tickers[0])
        set_pending_action(chat_id, None)
        await _send_watchlist(chat_id)
        return

    if action == "alert_add":
        m = re.search(r"\b([A-Z]{3,4})\b\s+(above|below)\s+([0-9]+(?:\.[0-9]+)?)", clean, re.I)
        if not m:
            await send_message(chat_id, "Ví dụ: <code>VCB above 100</code>.")
            return
        alert_id = add_alert(chat_id, m.group(1), m.group(2).lower(), float(m.group(3)))
        set_pending_action(chat_id, None)
        await send_message(chat_id, f"✅ Đã tạo cảnh báo #{alert_id}.", alerts_menu())
        return

    if action == "alert_del":
        m = re.search(r"\b(\d+)\b", clean)
        if not m:
            await send_message(chat_id, "Gửi số ID cảnh báo, ví dụ <code>12</code>.")
            return
        disable_alert(int(m.group(1)), chat_id)
        set_pending_action(chat_id, None)
        await send_message(chat_id, "✅ Đã tắt cảnh báo.", alerts_menu())
        return

    if action == "document":
        await send_message(chat_id, "Hãy gửi PDF/Word/Excel/CSV/TXT/ảnh ngay trong chat để tôi nạp vào RAG.")
        return


async def _download_telegram_file(file_id: str, filename: str) -> str:
    data = await telegram_call("getFile", {"file_id": file_id})
    file_path = data["result"]["file_path"]
    if int(data["result"].get("file_size", 0)) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError("File quá lớn.")
    token = _token()
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    base = Path(os.getenv("TELEGRAM_DOCUMENT_DIR", "/data/documents" if os.path.isdir("/data") else "./data/documents"))
    base.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    path = base / safe_name
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = 0
            with path.open("wb") as f:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("File vượt quá giới hạn tải xuống.")
                    f.write(chunk)
    return str(path)


async def _handle_document(message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    if not _ok_update_user(message):
        await send_message(chat_id, "🔒 Bot đang ở chế độ private. Dùng /id để lấy Telegram ID.")
        return
    doc = message.get("document")
    if not doc:
        return
    name = doc.get("file_name", "telegram_file")
    try:
        path = await _download_telegram_file(doc["file_id"], name)
        await send_message(chat_id, f"📄 Đã nhận <b>{html.escape(name)}</b>. Đang nạp vào RAG…")
        count = await asyncio.to_thread(ingest_document, path)
        await send_message(chat_id, f"✅ Đã nạp <b>{html.escape(name)}</b>: {count} chunks.", main_menu())
    except Exception as exc:
        await send_message(chat_id, f"❌ Nạp tài liệu lỗi: {html.escape(str(exc))}", main_menu())


async def handle_message(message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    user = message.get("from") or {}
    upsert_user(chat_id, user)

    if not allowed_user(chat_id, int(user.get("id", 0))):
        text = message.get("text", "")
        if text.strip().lower().startswith("/id"):
            await _handle_command(message, "/id")
        else:
            await send_message(chat_id, "🔒 Bot cá nhân đang khóa. Gửi /id để lấy Telegram ID rồi thêm vào TELEGRAM_ALLOWED_USER_IDS.")
        return

    if message.get("document"):
        await _handle_document(message)
        return

    text = message.get("text", "").strip()
    if not text:
        return

    pending = get_pending_action(chat_id)
    if text.startswith("/"):
        await _handle_command(message, text)
    elif pending:
        await _handle_action(chat_id, pending, text)
    else:
        await _ask_ai(chat_id, text)


async def handle_callback(query: dict[str, Any]) -> None:
    await answer_callback(query.get("id", ""))
    message = query.get("message") or {}
    chat_id = int(message.get("chat", {}).get("id", 0))
    user = query.get("from") or {}
    upsert_user(chat_id, user)

    if not allowed_user(chat_id, int(user.get("id", 0))):
        await send_message(chat_id, "🔒 Bot cá nhân đang khóa. Gửi /id.")
        return

    data = str(query.get("data", ""))

    if data == "menu":
        await send_message(chat_id, "<b>TCBS Quant Assistant</b>", main_menu())
        return

    if data.startswith("act:"):
        action = data.split(":", 1)[1]
        if action == "tcbs":
            await _start_tcbs(chat_id)
            return
        if action == "status":
            from app.tcbs.oauth import connected
            client = TCBSMCPClient()
            await send_message(
                chat_id,
                f"<b>TRẠNG THÁI</b>\n"
                f"Telegram: ✅\nTCBS OAuth: {'✅' if connected() else '❌'}\n"
                f"TCBS token: {'✅' if client.configured else '❌'}\n"
                f"Watchlist: {len(list_watch(chat_id))} mã",
                main_menu(),
            )
            return
        if action == "watch":
            await send_message(chat_id, "<b>⭐ WATCHLIST</b>", watch_menu())
            return
        if action == "alerts":
            await send_message(chat_id, "<b>🚨 CẢNH BÁO</b>", alerts_menu())
            return
        if action == "document":
            set_pending_action(chat_id, "document")
            await send_message(chat_id, "📄 Gửi tài liệu trực tiếp vào Telegram. PDF/Word/Excel/CSV/TXT/ảnh đều được hỗ trợ.")
            return
        set_pending_action(chat_id, action)
        prompts = {
            "analyze": "Gửi mã cần phân tích, ví dụ <code>VCB</code>.",
            "compare": "Gửi các mã cần so sánh, ví dụ <code>VCB BID CTG MBB</code>.",
            "screen": "Gửi universe, ví dụ <code>VCB BID CTG MBB TCB VPB ACB</code>.",
            "technical": "Gửi mã, ví dụ <code>VCB</code>.",
            "valuation": "Gửi mã, ví dụ <code>VCB</code>.",
            "bank": "Gửi mã ngân hàng, ví dụ <code>VCB</code>.",
            "news": "Gửi mã, ví dụ <code>VCB</code>.",
            "foreign": "Gửi mã, ví dụ <code>VCB</code>.",
            "owners": "Gửi mã, ví dụ <code>VCB</code>.",
            "dividend": "Gửi mã, ví dụ <code>VCB</code>.",
            "ai": "Gửi câu hỏi cho AI.",
            "watch_add": "Gửi mã cần thêm.",
            "watch_del": "Gửi mã cần xóa.",
            "alert_add": "Ví dụ <code>VCB above 100</code>.",
            "alert_del": "Gửi ID cảnh báo cần tắt.",
        }
        await send_message(chat_id, prompts.get(action, "Gửi yêu cầu."), main_menu())
        return

    if re.fullmatch(r"(tech|val|bank|news|foreign|raw):[A-Z]{3,4}", data):
        kind, ticker = data.split(":")
        query_map = {
            "tech": f"phân tích kỹ thuật {ticker} RSI MACD MA",
            "val": f"định giá {ticker} PE PB ROE EPS",
            "bank": f"{ticker} NIM CIR NPL LDR ngân hàng",
            "news": f"tin tức sự kiện {ticker}",
            "foreign": f"khối ngoại {ticker}",
            "raw": f"tổng quan {ticker} giá hiện tại",
        }
        if kind == "raw":
            await _send_tool(chat_id, query_map[kind], "📊 DỮ LIỆU TCBS")
        else:
            title = {
                "tech": "📈 PHÂN TÍCH KỸ THUẬT",
                "val": "💰 ĐỊNH GIÁ",
                "bank": "🏦 CHỈ SỐ NGÂN HÀNG",
                "news": "📰 TIN TỨC",
                "foreign": "🌍 KHỐI NGOẠI",
            }[kind]
            await _send_tool(chat_id, query_map[kind], title)
        return

    m = re.fullmatch(r"watchadd:([A-Z]{3,4})", data)
    if m:
        add_watch(chat_id, m.group(1))
        await _send_watchlist(chat_id)
        return

    if data == "watch:list":
        await _send_watchlist(chat_id)
        return

    if data == "alerts:list":
        rows = list_alerts(chat_id)
        if not rows:
            await send_message(chat_id, "🚨 Chưa có cảnh báo.", alerts_menu())
            return
        lines = ["<b>🚨 CẢNH BÁO</b>", ""]
        for x in rows:
            lines.append(
                f"#{x['id']} {html.escape(x['ticker'])} "
                f"{html.escape(x['direction'])} {_fmt(x['target'])} "
                f"| {'ON' if x['enabled'] else 'OFF'}"
            )
        await send_message(chat_id, "\n".join(lines), alerts_menu())
        return


async def _process_update(update: dict[str, Any]) -> None:
    try:
        if update.get("callback_query"):
            await handle_callback(update["callback_query"])
        elif update.get("message"):
            await handle_message(update["message"])
    except Exception:
        logger.exception("Telegram update processing failed")


async def handle_telegram_update(update: dict[str, Any]) -> None:
    task = asyncio.create_task(_process_update(update))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
