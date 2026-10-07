import os
import shutil
import logging
import ipaddress
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Request, Query
from app.models.schemas import QueryRequest, QueryResponse, UploadResponse, Source
from app.rag.pipeline import ingest_document, ingest_raw_text, query_pipeline
from app.rag.vector_store import reset_db, delete_document, list_documents
from app.rules.manager import get_business_rules, save_business_rules
from app.llm.generator import reset_llm, get_backend
from app.llm.settings import save_model_settings, normalize_model_path, DEFAULT_MODEL_PATH, DEFAULT_MODEL_TYPE
from app.tcbs.client import TCBSMCPClient, TCBSMCPError
from app.tcbs.oauth import connect_and_list_tools, receive_callback, connected, disconnect
from app.quant.analyzer import analyze_ticker
from app.quant.compare import compare_tickers
from app.quant.screener import screen_tickers

logger = logging.getLogger(__name__)

router = APIRouter()

# Ensure the upload directory exists
UPLOAD_DIR = os.path.join(os.getcwd(), "data", "documents")
os.makedirs(UPLOAD_DIR, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp",
    ".csv", ".xlsx", ".xls", ".docx", ".doc", ".txt", ".md"
}

# --- MODEL & STORAGE CONFIGURATION ENDPOINTS ---
@router.get("/settings/model/browse")
def browse_model_files(request: Request, path: str | None = None, offset: int = Query(0, ge=0)):
    # This unauthenticated local app must not expose its filesystem to remote clients.
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(status_code=403, detail="The model picker is available on the TDnook host only.")
    from app.llm.browser import browse_models
    try:
        return browse_models(path, offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=403, detail="Cannot read this folder. Check folder permissions.") from exc


@router.get("/settings/model")
def get_model_settings():
    """
    Get current LLM model storage path and runtime status.
    """
    path = normalize_model_path(os.getenv("LOCAL_MODEL_PATH", DEFAULT_MODEL_PATH))
    model_type = os.getenv("LOCAL_MODEL_TYPE", DEFAULT_MODEL_TYPE)
    exists = os.path.exists(path) if path else False
    is_dir = os.path.isdir(path) if exists else False
    
    target_backend = "Unknown"
    if exists:
        if is_dir:
            target_backend = "mlx_lm (Apple Silicon Metal)"
        elif path.endswith(".gguf") or "gguf" in path.lower():
            target_backend = "llama_cpp (GGUF Binary)"
        else:
            target_backend = "ctransformers / generic"
            
    return {
        "local_model_path": path,
        "local_model_type": model_type,
        "exists": exists,
        "is_directory": is_dir,
        "backend": get_backend() or target_backend,
        "target_engine": target_backend,
        "model_n_ctx": int(os.getenv("MODEL_N_CTX", 8192)),
        "model_temperature": float(os.getenv("MODEL_TEMPERATURE", 0.3))
    }

@router.post("/settings/model")
def update_model_settings(payload: dict = Body(...)):
    """
    Update LOCAL_MODEL_PATH and LOCAL_MODEL_TYPE in environment and .env file.
    """
    try:
        save_model_settings(payload.get("local_model_path"), payload.get("local_model_type"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Could not persist model settings: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save model settings to .env.") from exc
    reset_llm()
    return {"status": "success", **get_model_settings()}


# --- BUSINESS RULES ENDPOINTS ---
@router.get("/tcbs/status")
def tcbs_status():
    """Return local TCBS MCP configuration status without exposing credentials."""
    client = TCBSMCPClient()
    return {
        "enabled": os.getenv("TCBS_MCP_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
        "configured": client.configured,
        "connected": connected(),
        "url": client.url,
        "auth": "oauth2_access_token" if client.configured else "not_configured",
    }


@router.get("/tcbs/tools")
def tcbs_tools():
    """Discover the currently exposed tools from the official TCBS MCP server."""
    client = TCBSMCPClient()
    if not client.configured:
        raise HTTPException(status_code=401, detail="TCBS_MCP_ACCESS_TOKEN is not configured.")
    try:
        tools = client.list_tools()
        return {"tools": tools, "count": len(tools)}
    except TCBSMCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tcbs/connect")
async def tcbs_connect():
    """Start TCBS MCP OAuth and verify the connection."""
    try:
        tools = await connect_and_list_tools()
        return {"status": "connected", "tools": tools, "count": len(tools)}
    except Exception as exc:
        logger.error("TCBS connection failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"TCBS connection failed: {exc}") from exc


@router.get("/tcbs/oauth/callback")
async def tcbs_oauth_callback(code: str | None = None, state: str | None = None, iss: str | None = None):
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code.")
    if not receive_callback(code, state, iss):
        raise HTTPException(status_code=409, detail="No pending TCBS connection.")
    return {"status": "received", "message": "Đã nhận xác thực TCBS."}


@router.post("/tcbs/disconnect")
def tcbs_disconnect():
    disconnect()
    return {"status": "disconnected"}


@router.get("/rules")
def get_rules():
    """
    Get current business rules and guardrail settings.
    """
    return get_business_rules()

@router.post("/rules")
def update_rules(rules: dict = Body(...)):
    """
    Update business rules and guardrails.
    """
    success = save_business_rules(rules)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save business rules.")
    return {"status": "success", "message": "Business rules updated successfully."}


# --- DOCUMENT MANAGEMENT ENDPOINTS ---
@router.get("/documents")
def get_documents():
    """
    Get the list of all ingested documents in the vector database.
    """
    files = list_documents()
    return {"documents": files, "count": len(files)}

@router.delete("/documents")
def clear_all_documents():
    """
    Clear all documents and vectors from the database.
    """
    reset_db()
    if os.path.exists(UPLOAD_DIR):
        for f in os.listdir(UPLOAD_DIR):
            fpath = os.path.join(UPLOAD_DIR, f)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    return {"status": "success", "message": "All documents and vectors have been cleared."}

@router.delete("/documents/{filename}")
def remove_document(filename: str):
    """
    Delete a specific document and its chunks.
    """
    delete_document(filename)
    fpath = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
        except Exception:
            pass
    return {"status": "success", "message": f"Document '{filename}' removed."}

@router.post("/documents/raw-text", response_model=UploadResponse)
def upload_raw_text(payload: dict = Body(...)):
    """
    Endpoint for Admin/User to ingest handwritten/manual text directly.
    """
    title = payload.get("title", "manual_knowledge").strip()
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text content cannot be empty.")
        
    try:
        chunks = ingest_raw_text(title, text)
        clean_title = f"{title}.txt" if not title.endswith(".txt") else title
        return UploadResponse(
            status="success",
            filename=clean_title,
            chunks=chunks
        )
    except Exception as e:
        logger.error(f"Error ingesting raw text: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from app.models.schemas import QueryRequest, QueryResponse, UploadResponse, UserFileParseResponse, Source
from app.rag.loader import extract_pages_from_file

TEMP_USER_DIR = os.path.join(os.getcwd(), "data", "temp_user_uploads")
os.makedirs(TEMP_USER_DIR, exist_ok=True)

@router.post("/documents/parse-user-file", response_model=UserFileParseResponse)
async def parse_user_file(file: UploadFile = File(...)):
    """
    Endpoint for User Portal: Parses user attached files/images (via OCR or Native) 
    temporarily for conversation context WITHOUT saving into permanent system knowledge base.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
        
    temp_path = os.path.join(TEMP_USER_DIR, f"temp_{os.getpid()}_{file.filename}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logger.info(f"Parsing temporary user document: {file.filename}")
        pages = extract_pages_from_file(temp_path)
        
        if not pages:
            raise ValueError(f"Could not extract readable text or image content from {file.filename}.")
            
        full_text = "\n\n".join([p["text"].strip() for p in pages if p.get("text", "").strip()])
        
        return UserFileParseResponse(
            status="success",
            filename=file.filename,
            text=full_text,
            pages=len(pages),
            char_count=len(full_text)
        )
    except Exception as e:
        logger.error(f"Error parsing user document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    Admin Endpoint to permanently upload and ingest multi-format files into system vector store.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
        
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    try:
        # Save file to disk
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logger.info(f"Admin saved uploaded file to {file_path}")
        
        # Process and ingest multi-format document into permanent system knowledge
        num_chunks = ingest_document(file_path)
        
        return UploadResponse(
            status="success",
            filename=file.filename,
            chunks=num_chunks
        )
    except Exception as e:
        logger.error(f"Error uploading and ingesting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
@router.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """
    Endpoint to query documents with support for:
    1. Active user attached document
    2. Cross-referencing with system knowledge vector DB
    """
    try:
        result = query_pipeline(
            request.question,
            filename=request.filename,
            user_document_text=request.user_document_text,
            user_document_name=request.user_document_name
        )
        
        sources = [Source(**s) for s in result["sources"]]
        
        return QueryResponse(
            answer=result["answer"],
            sources=sources
        )
    except Exception as e:
        logger.error(f"Error querying documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- QUANT ENGINE ENDPOINTS ---
@router.get("/quant/analyze/{ticker}")
def quant_analyze(ticker: str):
    """Run the deterministic TCBS quantitative analysis for one ticker."""
    ticker = ticker.strip().upper()
    if not ticker.isalpha() or not 3 <= len(ticker) <= 4:
        raise HTTPException(status_code=400, detail="Ticker không hợp lệ.")
    try:
        return analyze_ticker(ticker)
    except Exception as exc:
        logger.error("Quant analysis failed for %s: %s", ticker, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/quant/compare")
def quant_compare(payload: dict = Body(...)):
    """Compare several tickers using the same deterministic scoring engine."""
    tickers = payload.get("tickers", [])
    if not isinstance(tickers, list) or not tickers:
        raise HTTPException(status_code=400, detail="Body phải có tickers: [\"VCB\", \"BID\"]")
    if len(tickers) > 20:
        raise HTTPException(status_code=400, detail="Tối đa 20 mã mỗi lần so sánh.")
    try:
        return compare_tickers([str(x) for x in tickers])
    except Exception as exc:
        logger.error("Quant comparison failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/quant/screen")
def quant_screen(payload: dict = Body(...)):
    """Rank a supplied universe of tickers. No universe is silently invented."""
    tickers = payload.get("tickers", [])
    if not isinstance(tickers, list) or not tickers:
        raise HTTPException(status_code=400, detail="Body phải có tickers: [\"VCB\", \"BID\", ...]")
    if len(tickers) > 50:
        raise HTTPException(status_code=400, detail="Tối đa 50 mã mỗi lần screening.")
    try:
        return screen_tickers([str(x) for x in tickers])
    except Exception as exc:
        logger.error("Quant screening failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
