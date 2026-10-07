import os
import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model = None

def get_model():
    global _model
    if _model is None:
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info(f"Loading local embedding model: {model_name}")
        _model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded successfully.")
    return _model

def get_embedding(text: str) -> list[float]:
    """
    Generates an embedding for a given text using local SentenceTransformer.
    
    Args:
        text (str): The text to embed.
        
    Returns:
        list[float]: The embedding vector.
    """
    try:
        model = get_model()
        embedding = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise e

def get_query_embedding(text: str) -> list[float]:
    """
    Generates an embedding for a query using local SentenceTransformer.
    (Same model, same encoding - kept for API compatibility.)
    
    Args:
        text (str): The query text to embed.
        
    Returns:
        list[float]: The embedding vector.
    """
    return get_embedding(text)

def get_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Generates embeddings for a batch of texts efficiently.
    
    Args:
        texts (list[str]): List of texts to embed.
        batch_size (int): Batch size for processing.
        
    Returns:
        list[list[float]]: List of embedding vectors.
    """
    try:
        model = get_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False
        )
        return embeddings.tolist()
    except Exception as e:
        logger.error(f"Error generating batch embeddings: {e}")
        raise e
