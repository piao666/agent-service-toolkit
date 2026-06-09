from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings

from rag.config import rag_settings


def get_embedding_model(
    provider: str | None = None,
    model_path: str | Path | None = None,
    device: str = "cpu",
) -> Embeddings:
    """Return the embedding client used by enterprise Chroma ingest and retrieval."""
    selected_provider = (provider or rag_settings.EMBEDDING_PROVIDER).lower()
    if selected_provider != "local":
        raise ValueError(
            f"Unsupported embedding provider '{selected_provider}'. "
            "Phase 1 defaults to local embeddings only."
        )

    resolved_path = Path(model_path or rag_settings.local_embedding_model_path).expanduser()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Local embedding model path does not exist: {resolved_path}")

    return HuggingFaceEmbeddings(
        model_name=str(resolved_path),
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )

