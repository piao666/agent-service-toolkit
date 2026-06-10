from typing import Any

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    source: str
    title: str | None = None
    doc_type: str | None = None
    chunk_id: str
    chunk_index: int | None = None
    distance: float
    relevance_score: float
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_preview: str
    page_content: str


class IngestStats(BaseModel):
    document_count: int
    chunk_count: int
    persist_dir: str
    collection_name: str
    embedding_provider: str
    model_path: str
