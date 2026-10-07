import os
import logging

logger = logging.getLogger(__name__)

_model = None


def get_model():
    global _model
    if _model is None:
        # Heavy ML dependencies are intentionally imported only when RAG
        # actually needs embeddings. This keeps the Railway webhook process
        # lightweight and prevents Torch/CUDA from loading during startup.
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info("Loading local embedding model: %s", model_name)
        _model = SentenceTransformer(model_name, device=os.getenv("EMBEDDING_DEVICE", "cpu"))
        logger.info("Embedding model loaded successfully.")
    return _model


def get_embedding(text: str) -> list[float]:
    try:
        model = get_model()
        embedding = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.error("Error generating embedding: %s", e, exc_info=True)
        raise


def get_query_embedding(text: str) -> list[float]:
    return get_embedding(text)


def get_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    try:
        model = get_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
        )
        return embeddings.tolist()
    except Exception as e:
        logger.error("Error generating batch embeddings: %s", e, exc_info=True)
        raise
