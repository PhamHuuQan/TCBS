# Railway B1 deployment

## Target architecture

Telegram -> Railway FastAPI webhook -> TCBS MCP / Quant Engine / BCTC-RAG -> Gemini API.

The Railway service uses requirements-railway.txt and the railway.json start/healthcheck configuration.

## Required secrets

Set these on the Railway service:

    TELEGRAM_TOKEN=<existing BotFather token is accepted>
    TELEGRAM_ALLOWED_USER_IDS=<your numeric Telegram user id>
    GEMINI_API_KEY=<your Gemini API key>

The application also accepts TELEGRAM_BOT_TOKEN instead of TELEGRAM_TOKEN.

## Public endpoints

Generate a Railway public domain for the service. The app derives:

    https://<RAILWAY_PUBLIC_DOMAIN>/telegram/webhook/<stable-secret>
    https://<RAILWAY_PUBLIC_DOMAIN>/tcbs/oauth/callback

You may override these with TELEGRAM_WEBHOOK_URL and TCBS_OAUTH_REDIRECT_URI.

## Persistence

Attach a Railway Volume at:

    /data

The bot database defaults to /data/tcbs_telegram.db and documents to /data/documents. ChromaDB now automatically defaults to /data/vector_db whenever /data exists.

## TCBS

Use Telegram's Kết nối TCBS button. The user is redirected to TCBS OAuth and returns through the public callback. No TCBS password or iOTP is stored by the application.

## Railway Free-plan caveat

The current workspace has reached its service-provisioning limit, so a new fourth service cannot be created. The Railway configuration has therefore been staged onto the existing telegram-ai-bot service without applying it. Applying that staged change will replace the current service source with this repository.
