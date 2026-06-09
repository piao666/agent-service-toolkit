from pathlib import Path

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )

    EMBEDDING_PROVIDER: str = "local"
    LOCAL_EMBEDDING_MODEL_PATH: str = "./models/bge-small-zh-v1.5"
    CHROMA_PERSIST_DIR: str = "./chroma_enterprise"
    CHROMA_COLLECTION_NAME: str = "enterprise_knowledge_base"
    RAG_CHUNK_SIZE: int = 800
    RAG_CHUNK_OVERLAP: int = 120
    RAG_DEFAULT_TOP_K: int = 5

    @property
    def local_embedding_model_path(self) -> Path:
        return Path(self.LOCAL_EMBEDDING_MODEL_PATH).expanduser()


rag_settings = RagSettings()

