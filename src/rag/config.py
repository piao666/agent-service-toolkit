from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Phase 4D: default embedding switched to bge-m3 (HPC-verified, k=3=0.9545)
DEFAULT_LOCAL_EMBEDDING_MODEL_PATH = "./models/bge-m3"
DEFAULT_CHROMA_COLLECTION_NAME = "enterprise_kb_v1_official_docs_bge_m3"
DEFAULT_LOCAL_EMBEDDING_MODEL_NAME = "bge-m3"

# Embedding candidates (Phase 4C HPC A/B verified)
# - default: bge-m3 (1024-dim, k=5=0.9091, GPU=2.99GB)
# - high_precision: qwen3-embedding-0.6b (1024-dim, k=5=0.9091, GPU=5.57GB)
# - lightweight_fallback: bge-small-zh-v1.5 (512-dim, k=5=0.8182, GPU=0.47GB)

# Phase 4F: Internal engineering corpus (bge-m3)
# - enabled=false, allowed_for_answer=false (eval/demo only)
# - built on HPC, same bge-m3 embedding as official_docs
DEFAULT_INTERNAL_CHROMA_COLLECTION_NAME = "enterprise_kb_v1_internal_engineering_bge_m3"


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
    CHROMA_PERSIST_DIR: str = "./storage/chroma_enterprise_kb_v1_bge_m3"
    CHROMA_COLLECTION_NAME: str = DEFAULT_CHROMA_COLLECTION_NAME
    # Phase 4F: Internal engineering corpus
    CHROMA_INTERNAL_PERSIST_DIR: str = "./storage/chroma_enterprise_kb_v1_internal_bge_m3"
    CHROMA_INTERNAL_COLLECTION_NAME: str = DEFAULT_INTERNAL_CHROMA_COLLECTION_NAME
    ENTERPRISE_CHROMA_COLLECTION: str | None = None
    # Phase 4D: reranker NOT enabled (deferred to next phase)
    RERANKER_ENABLED: bool = False
    ENTERPRISE_RAG_POLICY_MODE: str = "baseline"
    ENTERPRISE_STRUCTURED_RETRIEVAL_MODE: str = "off"  # structured retrieval: "off" | "metadata_symbol"
    ENTERPRISE_MEMORY_MODE: str = "off"
    ENTERPRISE_MEMORY_MAX_TURNS: int = 5
    ENTERPRISE_MEMORY_MAX_ANSWER_CHARS: int = 1000
    ENTERPRISE_EVIDENCE_VERIFIER_MODE: str = "off"
    ENTERPRISE_EVIDENCE_SAFE_FALLBACK: bool = False
    ENTERPRISE_EVIDENCE_MIN_SCORE: float = 0.30
    ENTERPRISE_EVIDENCE_HIGH_SCORE: float = 0.60
    ENTERPRISE_AGENT_GRAPH_MODE: str = "legacy"
    ENTERPRISE_LLM_JUDGE_MODE: str | None = None
    ENTERPRISE_JUDGE_MODE: str = "rule_based_fallback"
    ENTERPRISE_PLANNER_MODE: str = "debug_only"
    ENTERPRISE_MULTI_HOP_MODE: str = "off"  # multi-hop retrieval: "off" | "rule_based"
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

    @property
    def evidence_verifier_mode(self) -> str:
        mode = self.ENTERPRISE_EVIDENCE_VERIFIER_MODE.strip().lower()
        return mode if mode in {"off", "rule_based"} else "off"

    @property
    def agent_graph_mode(self) -> str:
        # Read the process environment first so an explicitly configured service
        # instance cannot be shadowed by a value loaded from .env at import time.
        configured_mode = os.getenv(
            "ENTERPRISE_AGENT_GRAPH_MODE",
            self.ENTERPRISE_AGENT_GRAPH_MODE,
        )
        mode = configured_mode.strip().lower()
        return mode if mode in {"legacy", "custom_graph"} else "legacy"

    @property
    def judge_mode(self) -> str:
        configured_mode = (
            os.getenv("ENTERPRISE_LLM_JUDGE_MODE")
            or os.getenv("ENTERPRISE_JUDGE_MODE")
            or self.ENTERPRISE_LLM_JUDGE_MODE
            or self.ENTERPRISE_JUDGE_MODE
            or "rule_based_fallback"
        )
        mode = configured_mode.strip().lower()
        return mode if mode in {"off", "rule_based_fallback"} else "rule_based_fallback"

    @property
    def multi_hop_mode(self) -> str:
        configured_mode = (
            os.getenv("ENTERPRISE_MULTI_HOP_MODE")
            or self.ENTERPRISE_MULTI_HOP_MODE
            or "off"
        )
        mode = configured_mode.strip().lower()
        return mode if mode in {"off", "rule_based"} else "off"

    @property
    def planner_mode(self) -> str:
        configured_mode = (
            os.getenv("ENTERPRISE_PLANNER_MODE")
            or self.ENTERPRISE_PLANNER_MODE
            or "debug_only"
        )
        mode = configured_mode.strip().lower()
        return mode if mode in {"active", "debug_only"} else "debug_only"


rag_settings = RagSettings()
