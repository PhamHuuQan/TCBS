import os
import chromadb
from chromadb.config import Settings
import logging

logger = logging.getLogger(__name__)

_chroma_client = None

def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        default_path = "/data/vector_db" if os.path.isdir("/data") else "./data/vector_db"
        db_path = os.getenv("VECTOR_DB_PATH", default_path)
        os.makedirs(db_path, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=db_path)
        logger.info(f"ChromaDB initialized at: {db_path}")
    return _chroma_client

def get_collection(name="docurag_collection"):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)

def add_chunks_to_db(chunks: list[dict], embeddings: list[list[float]], collection_name="docurag_collection"):
    """
    Adds text chunks and their embeddings to the Chroma vector database.
    """
    if not chunks:
        raise ValueError(
            "No chunks to add to the database. "
            "The PDF may contain no extractable text (e.g., scanned/image-only PDF), "
            "or the chunking step produced no output."
        )
    if not embeddings:
        raise ValueError(
            "No embeddings generated for the chunks. "
            "Check the embedding model and input texts."
        )
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Chunk count ({len(chunks)}) does not match embedding count ({len(embeddings)})."
        )
    
    non_empty_embeddings = [e for e in embeddings if e and len(e) > 0]
    if len(non_empty_embeddings) != len(embeddings):
        raise ValueError(
            f"Some embeddings are empty. Got {len(embeddings) - len(non_empty_embeddings)} empty vectors."
        )
    
    try:
        collection = get_collection(collection_name)
        
        ids = [f"{chunk['metadata']['filename']}_{chunk['metadata']['chunk_id']}" for chunk in chunks]
        documents = [chunk['text'] for chunk in chunks]
        metadatas = [chunk['metadata'] for chunk in chunks]
        
        logger.info(
            f"Inserting {len(chunks)} chunks into Chroma collection '{collection_name}' "
            f"(embedding_dim={len(embeddings[0])})..."
        )
        
        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        logger.info(f"Successfully added {len(chunks)} chunks to vector database.")
    except Exception as e:
        logger.error(f"Error adding chunks to DB: {e}", exc_info=True)
        raise e

def reset_db(collection_name="docurag_collection"):
    """
    Deletes and recreates the collection to wipe all stored chunks.
    """
    client = get_chroma_client()
    try:
        client.delete_collection(name=collection_name)
        logger.info(f"Deleted ChromaDB collection: {collection_name}")
    except Exception as e:
        logger.warning(f"Could not delete collection '{collection_name}': {e}")
    return client.get_or_create_collection(name=collection_name)

def delete_document(filename: str, collection_name="docurag_collection"):
    """
    Deletes all chunks associated with a specific filename.
    """
    collection = get_collection(collection_name)
    try:
        collection.delete(where={"filename": filename})
        logger.info(f"Deleted document '{filename}' from collection '{collection_name}'.")
    except Exception as e:
        logger.error(f"Error deleting document '{filename}': {e}", exc_info=True)
        raise e

def list_documents(collection_name="docurag_collection") -> list[str]:
    """
    Returns a list of unique filenames currently in the vector DB.
    """
    collection = get_collection(collection_name)
    try:
        data = collection.get()
        if data and "metadatas" in data and data["metadatas"]:
            filenames = sorted(list({m.get("filename") for m in data["metadatas"] if m and "filename" in m}))
            return filenames
        return []
    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        return []

