from app.rag.vector_store import get_collection
from app.rag.embeddings import get_query_embedding
import os
import logging

logger = logging.getLogger(__name__)

def is_summary_query(query: str) -> bool:
    q = query.lower().strip()
    summary_keywords = [
        "tóm tắt", "tom tat", "tổng hợp", "tong hop", "tổng quan", "tong quan",
        "summary", "summarize", "overview", "toàn bộ tài liệu", "tat ca tai lieu",
        "nội dung chính", "noi dung chinh", "khái quát", "khai quat"
    ]
    return any(kw in q for kw in summary_keywords)

def retrieve_top_k(query: str, k: int = None, filename: str = None, collection_name="docurag_collection") -> list[dict]:
    """
    Retrieves the top K most similar chunks for a given query,
    or representative chunks across all documents if it is a summary request.
    """
    if k is None:
        k = int(os.getenv("TOP_K", 5))
        
    collection = get_collection(collection_name)
    
    # If the user asks for a summary, retrieve chunks from all available documents
    if is_summary_query(query):
        try:
            all_data = collection.get()
            if all_data and all_data['documents']:
                docs_by_file = {}
                for doc, meta in zip(all_data['documents'], all_data['metadatas']):
                    fn = meta.get('filename', 'unknown')
                    if filename and fn != filename:
                        continue
                    docs_by_file.setdefault(fn, []).append({
                        "text": doc,
                        "metadata": meta,
                        "distance": 0.0
                    })
                
                summary_chunks = []
                for fn, chunks in docs_by_file.items():
                    # Pick up to 2 representative chunks per document to cover entire library
                    summary_chunks.extend(chunks[:2])
                
                if summary_chunks:
                    logger.info(f"Summary query detected: Retrieved {len(summary_chunks)} chunks across {len(docs_by_file)} document(s).")
                    return summary_chunks
        except Exception as e:
            logger.warning(f"Failed to perform all-document summary fetch: {e}")

    try:
        # Standard vector semantic search
        query_embedding = get_query_embedding(query)
        where_filter = {"filename": filename} if filename else None
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where_filter
        )
        
        formatted_results = []
        if results and results['documents'] and len(results['documents']) > 0:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "text": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i] if 'distances' in results and results['distances'] else None
                })
                
        return formatted_results
    except Exception as e:
        logger.error(f"Error retrieving from DB: {e}")
        raise e

