import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router
from app.telegram import router as telegram_router, telegram_startup, telegram_shutdown
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

load_dotenv()

app = FastAPI(
    title="TDnook Enterprise",
    description="Minimalist Paper Document Reader & Assistant",
    version="2.1.0"
)

# Include API routes under /api or root
app.include_router(router)
app.include_router(telegram_router)

# Mount static folder
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_home():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "TDnook API is running. Static files not found."}

@app.on_event("startup")
async def startup_event():
    logger = logging.getLogger(__name__)
    logger.info("TDnook / TCBS Quant service starting")
    await telegram_startup()


@app.on_event("shutdown")
async def shutdown_event():
    await telegram_shutdown()

