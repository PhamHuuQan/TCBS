import os
import logging

logger = logging.getLogger(__name__)

_chroma_client = None


def _get_chromadb():
    # Chroma is loaded only when a vector operation is actually requested.
    import chromadb
    return chromadb


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        default_path = "/data/vector_db" if os.path.isdir("/data") else "./data/vector_db"
        db_path = os.getenv("VECTOR_DB_PATH", default_path)
        os.makedirs(db_path, exist_ok=True)
        chromadb = _get_chromadb()
        _chroma_client = chromadb.PersistentClient(path=db_path)
        logger.info("ChromaDB initialized at: %s", db_path)
    return _chroma_client


def get_collection(name="docurag_collection"):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)


def add_chunks_to_db(chunks: list[dict], embeddings: list[list[float]], collection_name="docurag_collection"):
    if not chunks:
        raise ValueError(
            "No chunks to add to the database. The PDF may contain no extractable text "
            "(e.g., scanned/image-only PDF), or the chunking step produced no output."
        )
    if not embeddings:
        raise ValueError("No embeddings generated for the chunks. Check the embedding model and input texts.")
    if len(chunks) != len(embeddings):
        raise ValueError(f"Chunk count ({len(chunks)}) does not match embedding count ({len(embeddings)}).")
    non_empty_embeddings = [e for e in embeddings if e and len(e) > 0]
    if len(non_empty_embeddings) != len(embeddings):
        raise ValueError(
            f"Some embeddings are empty. Got {len(embeddings) - len(non_empty_embeddings)} empty vectors."
        )
    try:
        collection = get_collection(collection_name)
        ids = [f"{chunk['metadata']['filename']}_{chunk['metadata']['chunk_id']}" for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [chunk["metadata"] for chunk in chunks]
        logger.info(
            "Inserting %s chunks into Chroma collection '%s' (embedding_dim=%s)...",
            len(chunks), collection_name, len(embeddings[0])
        )
        collection.add(embeddings=embeddings, documents=documents, metadatas=metadatas, ids=ids)
        logger.info("Successfully added %s chunks to vector database.", len(chunks))
    except Exception:
        logger.error("Error adding chunks to DB", exc_info=True)
        raise


def reset_db(collection_name="docurag_collection"):
    client = get_chroma_client()
    try:
        client.delete_collection(name=collection_name)
        logger.info("Deleted ChromaDB collection: %s", collection_name)
    except Exception as e:
        logger.warning("Could not delete collection '%s': %s", collection_name, e)
    return client.get_or_create_collection(name=collection_name)


def delete_document(filename: str, collection_name="docurag_collection"):
    collection = get_collection(collection_name)
    try:
        collection.delete(where={"filename": filename})
        logger.info("Deleted document '%s' from collection '%s'.", filename, collection_name)
    except Exception:
        logger.error("Error deleting document '%s' from collection '%s'.", filename, collection_name, exc_info=True)
        raise


def list_documents(collection_name="docurag_collection") -> list[str]:
    collection = get_collection(collection_name)
    try:
        data = collection.get()
        if data and data.get("metadatas"):
            return sorted({m.get("filename") for m in data["metadatas"] if m and m.get("filename")})
        return []
    except Exception:
        logger.error("Error listing documents", exc_info=True)
        return []
