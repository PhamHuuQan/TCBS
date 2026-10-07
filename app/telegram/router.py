
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from app.telegram.bot import handle_telegram_update
from app.telegram.bot import telegram_webhook_secret

router = APIRouter(tags=["telegram"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "tcbs-telegram"}


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    expected = telegram_webhook_secret()
    if secret != expected:
        raise HTTPException(status_code=404, detail="Not found")
    if x_telegram_bot_api_secret_token and x_telegram_bot_api_secret_token != expected:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    update = await request.json()
    await handle_telegram_update(update)
    return {"ok": True}
