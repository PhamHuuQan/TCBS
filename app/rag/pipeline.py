import os
import logging
from app.rag.loader import extract_pages_from_file
from app.rag.chunker import chunk_text
from app.rag.embeddings import get_embeddings_batch, get_embedding
from app.rag.vector_store import add_chunks_to_db
from app.rag.retriever import retrieve_top_k
from app.llm.generator import generate_answer
from app.rules.manager import check_guardrails_and_faq, get_business_rules

logger = logging.getLogger(__name__)

def ingest_document(file_path: str) -> int:
    """
    Ingests any supported document (PDF, Image, CSV, Excel, Word, TXT).
    """
    logger.info(f"===== Starting ingestion for: {file_path} =====")
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    pages = extract_pages_from_file(file_path)
    logger.info(f"Step 1 — Sections/Pages extracted: {len(pages)}")
    if not pages:
        raise ValueError(
            f"No text could be extracted from {os.path.basename(file_path)}. "
            "Please ensure the file contains readable text or clear images."
        )
    
    chunks = chunk_text(pages)
    logger.info(f"Step 2 — Chunks generated: {len(chunks)}")
    if not chunks:
        raise ValueError(f"No text chunks were produced from {os.path.basename(file_path)}.")
    
    texts = [chunk['text'] for chunk in chunks]
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", 32))
    
    logger.info(f"Step 3 — Generating {len(texts)} embeddings (batch_size={batch_size})...")
    embeddings = get_embeddings_batch(texts, batch_size=batch_size)
            
    if len(embeddings) != len(chunks):
        logger.warning("Mismatch in batch embeddings. Re-trying one-by-one as fallback.")
        embeddings = [get_embedding(t) for t in texts]
    
    logger.info("Step 4 — Adding to ChromaDB...")
    add_chunks_to_db(chunks, embeddings)
    
    logger.info(f"===== Ingestion complete. {len(chunks)} chunks stored. =====")
    return len(chunks)

def ingest_raw_text(title: str, text: str) -> int:
    """
    Ingests manual text entered by admin/user directly into vector store.
    """
    clean_title = title.strip() or "manual_snippet"
    if not clean_title.endswith(".txt"):
        clean_title = f"{clean_title}.txt"
        
    pages = [{
        "page_num": 1,
        "text": text.strip(),
        "filename": clean_title,
        "source": "manual_entry"
    }]
    
    chunks = chunk_text(pages)
    if not chunks:
        raise ValueError("Provided text is too short to chunk.")
        
    texts = [chunk['text'] for chunk in chunks]
    embeddings = get_embeddings_batch(texts)
    if len(embeddings) != len(chunks):
        embeddings = [get_embedding(t) for t in texts]
        
    add_chunks_to_db(chunks, embeddings)
    logger.info(f"Ingested manual text '{clean_title}' ({len(chunks)} chunks).")
    return len(chunks)

def query_pipeline(query: str, filename: str = None, user_document_text: str = None, user_document_name: str = None) -> dict:
    """
    Full RAG pipeline with:
    1. Business Guardrails & Direct FAQ
    2. Active User Document (Session Base)
    3. Cross-referencing with System Knowledge Vector Store
    4. Business Rules Strict Mode Enforcement
    """
    logger.info(f"Processing query: '{query}' (filter filename={filename}, user_doc={user_document_name})")
    
    # 1. Check Business Guardrails & Direct FAQ
    guardrail_res = check_guardrails_and_faq(query)
    if guardrail_res is not None:
        logger.info("Query answered directly by Business Guardrail / FAQ Rule.")
        return guardrail_res
        
    # 2. Retrieve relevant chunks from Vector DB (System Knowledge)
    retrieved_chunks = retrieve_top_k(query, filename=filename)
    logger.info(f"Retrieved {len(retrieved_chunks)} relevant system knowledge chunks.")
    
    rules = get_business_rules()
    strict_mode = rules.get("strict_mode", True)
    no_answer_msg = rules.get("no_answer_response", "Xin lỗi, thông tin này không có trong tài liệu được cung cấp.")
    
    # If in strict mode and neither user document nor system knowledge has content
    if strict_mode and not retrieved_chunks and not user_document_text:
        return {
            "answer": no_answer_msg,
            "sources": []
        }
    
    # 3. Generate answer using LLM guided by Business Rules and Multi-Language constraints
    answer = generate_answer(
        query,
        retrieved_chunks,
        user_document_text=user_document_text,
        user_document_name=user_document_name
    )
    
    sources = []
    
    # Add User Document as source if used
    if user_document_name and user_document_text:
        sources.append({
            "filename": f"[User File] {user_document_name}",
            "page": 1
        })
        
    # Add System Knowledge sources
    for chunk in retrieved_chunks:
        sources.append({
            "filename": chunk["metadata"]["filename"],
            "page": chunk["metadata"]["page"]
        })
    
    seen = set()
    unique_sources = []
    for s in sources:
        identifier = f"{s['filename']}_{s['page']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_sources.append(s)
            
    return {
        "answer": answer,
        "sources": unique_sources
    }
