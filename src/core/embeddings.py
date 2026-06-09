from langchain_core.embeddings import Embeddings

from rag.embeddings import get_embedding_model as get_local_embedding_model


def get_embedding_model() -> Embeddings:
    """Create the default embedding client used by Chroma ingest and retrieval."""
    return get_local_embedding_model()
