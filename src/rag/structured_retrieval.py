"""Structured retrieval infrastructure.

Provides metadata index lookup and symbol index search for targeted
query types (exact_metadata_lookup, code_api_config, citation_required_query).
Never replaces baseline dense — only injects structured candidates as boost.

Feature flag: ENTERPRISE_STRUCTURED_RETRIEVAL_MODE (default "off")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag.config import rag_settings

# ── Index file paths (KB v1: env-var only, no default old paths) ──
ROOT_DIR = Path(__file__).resolve().parents[2]
META_INDEX_PATH: Path | None = None
SYMBOL_INDEX_PATH: Path | None = None

# ── Query types that benefit from structured retrieval ──
STRUCTURED_QUERY_TYPES = {
    "exact_metadata_lookup",
    "code_api_config",
    "citation_required_query",
    "short_keyword",
}


def _load_meta_index() -> list[dict[str, Any]]:
    if META_INDEX_PATH is None or not META_INDEX_PATH.exists():
        return []
    return json.loads(META_INDEX_PATH.read_text(encoding="utf-8"))


def _load_sym_index() -> list[dict[str, Any]]:
    if SYMBOL_INDEX_PATH is None or not SYMBOL_INDEX_PATH.exists():
        return []
    return json.loads(SYMBOL_INDEX_PATH.read_text(encoding="utf-8"))


def search_metadata_index(query: str) -> dict[str, Any]:
    """Search metadata index for matching source_ids and chunk_ids."""
    meta = _load_meta_index()
    query_lower = query.lower()
    results: dict[str, Any] = {
        "matched_source_ids": [],
        "matched_chunk_ids": [],
        "matched_titles": [],
        "total_sources_searched": len(meta),
    }
    for entry in meta:
        sid = entry.get("source_id", "")
        # Check if query contains source_id or chunk_id patterns
        if sid and sid.lower() in query_lower:
            results["matched_source_ids"].append(sid)
        for cid in entry.get("chunk_ids", []):
            if cid and cid.lower() in query_lower:
                results["matched_chunk_ids"].append({"chunk_id": cid, "source_id": sid})
        for title in entry.get("titles", []):
            if title and title.lower() in query_lower:
                results["matched_titles"].append({"title": title, "source_id": sid})
    return results


def search_symbol_index(query: str) -> dict[str, Any]:
    """Search symbol index for matching code/config symbols."""
    symbols = _load_sym_index()
    query_lower = query.lower()
    query_terms = set(query_lower.split())
    matches: list[dict[str, Any]] = []
    seen_sids: set[str] = set()

    for sym in symbols:
        val = sym.get("value", "").lower()
        sid = sym.get("source_id", "")
        if not val:
            continue
        # Match: exact substring or term overlap
        if val in query_lower or any(t in val or val in t for t in query_terms if len(t) >= 3):
            if sid not in seen_sids:
                matches.append(sym)
                seen_sids.add(sid)

    return {
        "matched_symbols": matches[:20],
        "total_symbols_searched": len(symbols),
        "matched_source_ids": [m["source_id"] for m in matches[:10]],
    }


def structured_retrieve(
    query: str,
    query_type: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run structured retrieval for target query types.

    Returns debug info only — actual retrieval is done by the baseline
    dense path in retriever.py. This provides candidate source_ids that
    can be used to boost or inject additional chunks.
    """
    mode = rag_settings.ENTERPRISE_STRUCTURED_RETRIEVAL_MODE.lower()
    matched_source_ids: list[str] = []
    matched_chunk_ids: list[dict[str, str]] = []
    debug: dict[str, Any] = {
        "structured_retrieval_mode": mode,
        "structured_route": "none",
        "structured_injection_enabled": False,
        "metadata_index_used": False,
        "symbol_index_used": False,
        "citation_verifier_used": False,
        "structured_candidates_count": 0,
        "structured_candidates_injected_count": 0,
        "baseline_candidates_count": 0,
        "final_sources_count": 0,
        "baseline_preserved": True,
        "fallback_to_baseline": True,
        "deduped_count": 0,
        "injection_reason": "",
    }

    if mode == "off":
        return matched_source_ids, matched_chunk_ids, debug

    if query_type and query_type not in STRUCTURED_QUERY_TYPES:
        debug["structured_route"] = "query_type_excluded"
        return matched_source_ids, matched_chunk_ids, debug

    debug["structured_route"] = query_type or "unknown"
    debug["fallback_to_baseline"] = False

    # ── Metadata index lookup ──
    meta_result = search_metadata_index(query)
    if meta_result.get("matched_source_ids") or meta_result.get("matched_chunk_ids"):
        debug["metadata_index_used"] = True
        for sid in meta_result.get("matched_source_ids", []):
            if sid not in matched_source_ids:
                matched_source_ids.append(sid)
        for ch in meta_result.get("matched_chunk_ids", []):
            if isinstance(ch, dict) and ch.get("chunk_id"):
                matched_chunk_ids.append({"chunk_id": ch["chunk_id"], "source_id": ch.get("source_id", "")})

    # ── Symbol index lookup ──
    sym_result = search_symbol_index(query)
    if sym_result.get("matched_source_ids"):
        debug["symbol_index_used"] = True
        for sid in sym_result.get("matched_source_ids", []):
            if sid not in matched_source_ids:
                matched_source_ids.append(sid)

    # ── Citation verifier ──
    citation_terms = ["引用", "出处", "来源", "cite", "citation", "source", "reference", "证据"]
    if any(t in query.lower() for t in citation_terms):
        debug["citation_verifier_used"] = True

    debug["structured_candidates_count"] = len(matched_source_ids) + len(matched_chunk_ids)
    if matched_source_ids or matched_chunk_ids:
        debug["structured_injection_enabled"] = True
        debug["injection_reason"] = f"metadata={debug['metadata_index_used']}, symbol={debug['symbol_index_used']}"
    return matched_source_ids, matched_chunk_ids, debug


def materialize_structured_candidates(
    matched_source_ids: list[str],
    matched_chunk_ids: list[dict[str, str]],
    normalized_query: str,
    top_k: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Materialize structured candidates from Chroma."""
    from rag.vector_store import get_vector_store
    from rag.embeddings import get_embedding_model

    candidates: list[dict[str, Any]] = []
    mdebug: dict[str, Any] = {"attempted": len(matched_source_ids) + len(matched_chunk_ids), "succeeded": 0, "fallback": 0}

    if not matched_source_ids and not matched_chunk_ids:
        return candidates, mdebug

    try:
        store = get_vector_store(
            get_embedding_model(),
            persist_dir=rag_settings.CHROMA_PERSIST_DIR,
            collection_name=rag_settings.chroma_collection_name,
        )
        # Safe collection: Use safe chromadb collection.get() instead of similarity_search_with_score filter
        chroma_col = None
        try:
            # LangChain Chroma wraps a chromadb collection
            if hasattr(store, "_collection"):
                chroma_col = store._collection
            elif hasattr(store, "_client"):
                chroma_col = store._client.get_collection(rag_settings.chroma_collection_name)
        except Exception:
            pass

        seen: set[str] = set()

        # ── Source ID lookup: use collection.get(where={"source_id": ...}) ──
        if chroma_col is not None:
            for sid in matched_source_ids[:5]:
                if sid in seen:
                    continue
                seen.add(sid)
                try:
                    result = chroma_col.get(where={"source_id": sid}, limit=2, include=["documents", "metadatas"])
                    if result and result.get("ids"):
                        for i, cid in enumerate(result["ids"]):
                            if cid in seen:
                                continue
                            seen.add(cid)
                            meta = (result.get("metadatas") or [{}])[i] if i < len(result.get("metadatas") or []) else {}
                            doc_text = (result.get("documents") or [""])[i] if i < len(result.get("documents") or []) else ""
                            candidates.append(_mk_safe(cid, sid, meta, doc_text, "structured_metadata"))
                            mdebug["succeeded"] += 1
                except Exception:
                    pass

            for ch in matched_chunk_ids[:10]:
                cid = ch.get("chunk_id", "")
                if cid in seen:
                    continue
                seen.add(cid)
                try:
                    result = chroma_col.get(where={"chunk_id": cid}, limit=1, include=["documents", "metadatas"])
                    if result and result.get("ids"):
                        meta = (result.get("metadatas") or [{}])[0]
                        doc_text = (result.get("documents") or [""])[0]
                        candidates.append(_mk_safe(cid, ch.get("source_id", meta.get("source_id", "")), meta, doc_text, "structured_symbol"))
                        mdebug["succeeded"] += 1
                except Exception:
                    pass
        else:
            mdebug["error"] = "chroma_collection_unavailable"

    except Exception as e:
        mdebug["error"] = str(e)[:200]
        # Never crash — return empty candidates

    # Fallback: manifest preview
    if not candidates:
        try:
            manifest = json.loads(META_INDEX_PATH.read_text(encoding="utf-8"))
            for entry in manifest:
                if entry.get("source_id", "") in matched_source_ids:
                    cids = entry.get("chunk_ids", [])[:2]
                    for cid in cids:
                        if cid not in seen:
                            seen.add(cid)
                            candidates.append({
                                "chunk_id": cid, "source_id": entry["source_id"],
                                "title": (entry.get("titles") or [""])[0],
                                "doc_type": (entry.get("doc_types") or [""])[0],
                                "content": entry.get("sample_preview", ""),
                                "content_preview": entry.get("sample_preview", "")[:260],
                                "metadata": {"source_id": entry["source_id"]},
                                "relevance_score": 0.65, "retrieval_stage": "structured_manifest_fallback",
                                "structured_candidate": True, "materialized": True, "preview_only": True,
                            })
                            mdebug["succeeded"] += 1
                            mdebug["fallback"] += 1
        except Exception:
            pass

    return candidates[:top_k * 2], mdebug


def _mk_safe(
    chunk_id: str, source_id: str, metadata: dict, doc_text: str, stage: str
) -> dict[str, Any]:
    """Safe candidate factory (no doc object dependency)."""
    return {
        "chunk_id": chunk_id, "source_id": source_id,
        "title": metadata.get("title", ""), "doc_type": metadata.get("doc_type", ""),
        "content": doc_text,
        "content_preview": doc_text[:260],
        "metadata": metadata, "relevance_score": 0.85,
        "retrieval_stage": stage, "structured_candidate": True,
        "materialized": True, "preview_only": False,
    }
