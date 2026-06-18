from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LOCAL_EMBEDDING_MODEL_PATH = "./models/bge-small-zh-v1.5"
DEFAULT_CHROMA_COLLECTION_NAME = "enterprise_knowledge_base"
DEFAULT_LOCAL_EMBEDDING_MODEL_NAME = "bge-small-zh-v1.5"


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )

    EMBEDDING_PROVIDER: str = "local"
    LOCAL_EMBEDDING_MODEL_PATH: str = DEFAULT_LOCAL_EMBEDDING_MODEL_PATH
    LOCAL_EMBEDDING_MODEL_ROOT: str | None = None
    CHROMA_PERSIST_DIR: str = "./chroma_enterprise"
    CHROMA_COLLECTION_NAME: str = DEFAULT_CHROMA_COLLECTION_NAME
    ENTERPRISE_CHROMA_COLLECTION: str | None = None
    ENTERPRISE_RAG_POLICY_MODE: str = "baseline"
    ENTERPRISE_STRUCTURED_RETRIEVAL_MODE: str = "off"  # Phase 6F: "off" | "metadata_symbol"
    ENTERPRISE_MEMORY_MODE: str = "off"
    ENTERPRISE_MEMORY_MAX_TURNS: int = 5
    ENTERPRISE_MEMORY_MAX_ANSWER_CHARS: int = 1000
    RAG_CHUNK_SIZE: int = 800
    RAG_CHUNK_OVERLAP: int = 120
    RAG_DEFAULT_TOP_K: int = 5

    @property
    def local_embedding_model_path(self) -> Path:
        if self.LOCAL_EMBEDDING_MODEL_PATH != DEFAULT_LOCAL_EMBEDDING_MODEL_PATH:
            return Path(self.LOCAL_EMBEDDING_MODEL_PATH).expanduser()
        if self.LOCAL_EMBEDDING_MODEL_ROOT:
            return Path(self.LOCAL_EMBEDDING_MODEL_ROOT).expanduser() / DEFAULT_LOCAL_EMBEDDING_MODEL_NAME
        return Path(self.LOCAL_EMBEDDING_MODEL_PATH).expanduser()

    @property
    def chroma_collection_name(self) -> str:
        if self.CHROMA_COLLECTION_NAME != DEFAULT_CHROMA_COLLECTION_NAME:
            return self.CHROMA_COLLECTION_NAME
        return self.ENTERPRISE_CHROMA_COLLECTION or self.CHROMA_COLLECTION_NAME

    @property
    def memory_mode(self) -> str:
        mode = self.ENTERPRISE_MEMORY_MODE.strip().lower()
        return mode if mode in {"off", "buffer"} else "off"


rag_settings = RagSettings()
