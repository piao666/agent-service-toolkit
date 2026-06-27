"""Build local expanded materials chunks (no Chroma write, no LLM)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

from rag.config import rag_settings
from rag.splitter import split_documents

# ── Constants ──
SGG_DATA = r"E:\Python\sgg-data"
ML_DATA = r"E:\Python\Machine Learning"
OUT_DIR = ROOT / "data" / "knowledge_base" / "local_expanded_materials"
EVAL_DIR = ROOT / "data" / "knowledge_base" / "evaluation"
MANIFEST_DIR = ROOT / "data" / "knowledge_base" / "manifests"
FULL_TEXT_EXTS = {".pdf", ".docx", ".pptx", ".ipynb", ".py", ".md", ".txt"}
SKIP_CSV_EXTS = {".csv"}  # CSV 全部跳过，不解析

SGG_SOURCE_MAP = {
    "01-LangChain": "local_langchain_course_pdf",
    "02-LangChain": "local_langchain_course_pdf",
    "03-LangChain": "local_langchain_course_pdf",
    "04-LangChain": "local_langchain_course_pdf",
    "05-LangChain": "local_langchain_course_pdf",
    "06-LangChain": "local_langchain_course_pdf",
    "07-LangChain": "local_langchain_course_pdf",
    "尚硅谷大模型技术.pptx": "local_llm_course_pptx",
    "尚硅谷大模型技术之 Python": "local_python_llm_course_docx",
    "数据分析大模型笔记": "local_data_analysis_llm_notes_docx",
}
ML_SOURCE_MAP = {
    "尚硅谷大模型技术之数学基础": "local_math_foundation_docx",
    "尚硅谷大模型技术之机器学习": "local_machine_learning_course_docx",
    "1.hello": "local_machine_learning_course",
    "2.matplotlib": "local_machine_learning_course",
}
ML_DIR_MAP = {
    "Bayes": "local_machine_learning_course", "KMeans": "local_machine_learning_course",
    "KNN": "local_machine_learning_course", "Linear Regression": "local_machine_learning_course",
    "Logistic Regression": "local_machine_learning_course", "SVM": "local_machine_learning_course",
    "Tree": "local_machine_learning_course", "集成": "local_machine_learning_course",
}
DOMAIN_MAP = {
    "local_langchain_course_pdf": "langchain_agent",
    "local_llm_course_pptx": "llm_course",
    "local_python_llm_course_docx": "python_llm",
    "local_data_analysis_llm_notes_docx": "data_analysis",
    "local_machine_learning_course": "machine_learning",
    "local_machine_learning_course_docx": "machine_learning",
    "local_math_foundation_docx": "math_foundation",
    "local_ml_csv": "machine_learning",
}
EXCLUDE_EXTS = {".pkl", ".dot", ".wordipynb"}

KW_GROUPS = {
    "langchain_agent": ["LangChain", "Model IO", "Chains", "Memory", "Tools", "Agents",
                        "Retrieval", "PromptTemplate", "LLMChain", "ConversationBufferMemory",
                        "AgentExecutor", "Tool", "Retriever", "VectorStore", "RAG"],
    "machine_learning": ["线性回归", "逻辑回归", "KNN", "KMeans", "Bayes", "SVM",
                         "决策树", "随机森林", "集成学习", "XGBoost", "LightGBM",
                         "交叉验证", "过拟合", "正则化", "特征工程", "sklearn"],
    "python_math": ["Python", "Numpy", "Pandas", "Matplotlib", "函数", "类", "面向对象",
                    "装饰器", "异常处理", "线性代数", "概率", "导数", "梯度", "矩阵"],
    "llm_rag": ["大模型", "Transformer", "Embedding", "向量数据库", "检索", "召回",
                "chunk", "prompt", "Agent", "工具调用"],
}


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--roots", nargs="+", default=[SGG_DATA, ML_DATA])
    p.add_argument("--output-jsonl", default=str(OUT_DIR / "local_expanded_materials_chunks.jsonl"))
    p.add_argument("--manifest-output", default=str(MANIFEST_DIR / "local_expanded_materials_manifest.jsonl"))
    p.add_argument("--audit-output", default=str(EVAL_DIR / "local_expanded_materials_corpus_audit.json"))
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--execute", action="store_true")
    return p.parse_args()


def _resolve_source_id(fp: Path, root_str: str) -> str:
    fname = fp.name
    if "sgg-data" in root_str.lower():
        for prefix, sid in SGG_SOURCE_MAP.items():
            if fname.startswith(prefix):
                return sid
        return fname.rsplit(".", 1)[0] if "." in fname else fname
    if "Machine Learning" in root_str:
        for prefix, sid in ML_SOURCE_MAP.items():
            if fname.startswith(prefix):
                return sid
        pname = fp.parent.name
        if pname in ML_DIR_MAP:
            return ML_DIR_MAP[pname]
        return fname.rsplit(".", 1)[0] if "." in fname else fname
    return fp.stem


def _lang_detect(text: str, fname: str) -> str:
    has_cjk = any("一" <= c <= "鿿" for c in text[:500])
    has_ascii = any(c.isascii() and c.isalpha() for c in text[:500])
    if has_cjk:
        return "zh"
    if has_ascii:
        return "en"
    return "unknown"


def _csv_metadata(fp: Path) -> dict[str, Any] | None:
    """CSV 全部跳过，不做任何解析（策略：csv_excluded_by_policy）。"""
    return None


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def main():
    args = _parse_args()
    execute = bool(args.execute)
    dry_run = not execute
    now = datetime.now(DATETIME_UTC).isoformat()

    print(f"[信息] {'DRY-RUN' if dry_run else 'EXECUTE'} mode")

    from rag.document_loader import _load_file  # noqa: E402
    from langchain_core.documents import Document

    # ── Discover files ──
    to_ingest: list[tuple[Path, str, str]] = []  # (path, root_str, source_id)
    metadata_only: list[dict] = []
    skipped: list[dict] = []
    csv_skipped: list[dict] = []
    loader_errors: list[dict] = []

    for root_str in args.roots:
        root = Path(root_str)
        if not root.exists():
            continue
        for fp in sorted(root.rglob("*")):
            if not fp.is_file():
                continue
            ext = fp.suffix.lower()
            pname = fp.parent.name
            if any(p.startswith(".") or p in {".venv", ".idea", ".ipynb_checkpoints", "__pycache__"} for p in fp.parts):
                continue
            sid = _resolve_source_id(fp, root_str)

            if ext in EXCLUDE_EXTS:
                skipped.append({"path": str(fp), "source_id": sid, "reason": f"unsupported_extension:{ext}"})
                continue
            if ext in {".pkl"}:
                skipped.append({"path": str(fp), "source_id": sid, "reason": "binary_or_model_artifact"})
                continue
            if ext in SKIP_CSV_EXTS:
                csv_skipped.append({"path": str(fp), "source_id": sid, "reason": "csv_excluded_by_policy"})
                continue
            if ext in FULL_TEXT_EXTS:
                to_ingest.append((fp, root_str, sid))
            else:
                skipped.append({"path": str(fp), "source_id": sid, "reason": f"unsupported_extension:{ext}"})

    print(f"[信息] Full-text ingest: {len(to_ingest)}, CSV skipped: {len(csv_skipped)}, other skipped: {len(skipped)}")

    # ── Load & split ──
    all_chunks: list[dict] = []
    doc_hashes: dict[str, str] = {}
    chunk_id_counter: Counter = Counter()

    for fp, root_str, sid in to_ingest:
        try:
            docs = _load_file(fp)
        except Exception as e:
            loader_errors.append({"path": str(fp), "source_id": sid, "error": str(e)[:200]})
            continue

        if not docs:
            continue

        doc_hash = _content_hash("\n".join(d.page_content for d in docs))
        doc_hashes[str(fp)] = doc_hash

        for orig_doc in docs:
            orig_doc.metadata["source_id"] = sid
            orig_doc.metadata["domain"] = DOMAIN_MAP.get(sid, "unknown")
            orig_doc.metadata["file_path"] = str(fp)
            orig_doc.metadata["file_name"] = fp.name
            orig_doc.metadata["extension"] = fp.suffix.lower()
            orig_doc.metadata["document_hash"] = doc_hash

        chunks = split_documents(docs)
        for ci, chunk in enumerate(chunks):
            meta = dict(chunk.metadata)
            meta.setdefault("source_id", sid)
            meta.setdefault("domain", DOMAIN_MAP.get(sid, "unknown"))
            meta.setdefault("doc_type", fp.suffix.lstrip("."))
            meta.setdefault("title", fp.stem)
            meta.setdefault("file_path", str(fp))
            meta.setdefault("file_name", fp.name)
            meta.setdefault("extension", fp.suffix.lower())
            meta.setdefault("document_hash", doc_hash)
            meta.setdefault("section_path", str(fp.relative_to(Path(root_str))) if root_str else fp.name)
            lang = _lang_detect(chunk.page_content, fp.name)
            meta.setdefault("language", lang)
            meta.setdefault("created_by", "local_expanded_materials_ingest")
            meta.setdefault("ingest_version", "local_expanded_materials_v1")
            cid = hashlib.sha256(f"{meta['source_id']}:{meta['chunk_id']}:{ci}".encode()).hexdigest()[:24]
            meta["chunk_id"] = cid
            meta["chunk_index"] = ci
            meta["content_hash"] = _content_hash(chunk.page_content)
            chunk_id_counter[cid] += 1
            all_chunks.append({
                "chunk_id": cid, "source_id": sid,
                "doc_type": meta["doc_type"], "domain": meta["domain"],
                "title": meta["title"], "file_path": str(fp),
                "chunk_index": ci, "text_len": len(chunk.page_content),
                "text_preview": chunk.page_content[:200],
                "metadata": meta,
                "page_content": chunk.page_content,
            })

    # ── Audit ──
    sid_dist = Counter(c["source_id"] for c in all_chunks)
    dt_dist = Counter(c["doc_type"] for c in all_chunks)
    dom_dist = Counter(c["domain"] for c in all_chunks)
    fp_dist = Counter(c["file_path"] for c in all_chunks)
    lens = [c["text_len"] for c in all_chunks]
    empty = sum(1 for c in all_chunks if not c["metadata"].get("page_content", "").strip())
    dup_ids = {k: v for k, v in chunk_id_counter.items() if v > 1}

    # Keyword coverage
    kw_hits: dict[str, dict] = {}
    all_text = "\n".join(c["page_content"] for c in all_chunks).lower()
    all_sids = {c["source_id"] for c in all_chunks}
    for group, kws in KW_GROUPS.items():
        for kw in kws:
            if kw.lower() in all_text:
                matching_sids = {c["source_id"] for c in all_chunks if kw.lower() in c["page_content"].lower()}
                count = sum(1 for c in all_chunks if kw.lower() in c["page_content"].lower())
                kw_hits[kw] = {"chunk_count": count, "source_ids": sorted(matching_sids)}

    # Samples
    samples = sorted(all_chunks, key=lambda c: c["text_len"], reverse=True)[:50]
    sample_out = [{
        "source_id": s["source_id"], "doc_type": s["doc_type"], "domain": s["domain"],
        "file_path": s["file_path"], "chunk_id": s["chunk_id"],
        "text_len": s["text_len"], "text_preview": s["text_preview"],
        "metadata": {str(k): str(v)[:80] for k, v in s["metadata"].items()},
    } for s in samples]

    audit = {
        "generated_at": now,
        "execute": execute,
        "dry_run": dry_run,
        "csv_skipped_count": len(csv_skipped),
        "csv_skipped_files": csv_skipped,
        "total_input_files": len(to_ingest) + len(csv_skipped),
        "full_text_ingest_files": len(to_ingest),
        "metadata_only_files": 0,
        "skipped_files": len(skipped) + len(csv_skipped),
        "csv_metadata_only_count": 0,
        "unsupported_extension_count": len([s for s in skipped if "unsupported_extension" in s.get("reason", "")]),
        "total_chunks": len(all_chunks),
        "source_id_distribution": dict(sid_dist.most_common()),
        "doc_type_distribution": dict(dt_dist.most_common()),
        "domain_distribution": dict(dom_dist.most_common()),
        "file_path_distribution_top50": dict(fp_dist.most_common(50)),
        "chunk_length": {"min": min(lens) if lens else 0, "max": max(lens) if lens else 0,
                         "avg": round(sum(lens) / len(lens), 1) if lens else 0, "total_chars": sum(lens)},
        "empty_text_count": empty,
        "duplicate_chunk_id_count": len(dup_ids),
        "duplicate_chunk_ids": list(dup_ids.keys())[:10] if dup_ids else [],
        "unknown_source_count": 0,
        "loader_error_count": len(loader_errors),
        "loader_errors": loader_errors[:20],
        "skipped_files_with_reason": skipped + csv_skipped,
        "metadata_only_files_with_reason": metadata_only,
        "keyword_coverage": kw_hits,
        "samples": sample_out,
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    Path(args.audit_output).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if execute:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.output_jsonl, "w", encoding="utf-8", newline="\n") as f:
            for c in all_chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        manifest_records = [{
            "source_id": c["source_id"], "chunk_id": c["chunk_id"],
            "doc_type": c["doc_type"], "title": c["title"],
            "chunk_index": c["chunk_index"], "text_len": c["text_len"],
        } for c in all_chunks]
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.manifest_output, "w", encoding="utf-8", newline="\n") as f:
            for m in manifest_records:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"[信息] Chunks written: {len(all_chunks)}")

    # Print summary
    print(f"Chunks: {len(all_chunks)} | empty: {empty} | dup: {len(dup_ids)} | errors: {len(loader_errors)}")
    print(f"Sources: {dict(sid_dist.most_common())}")
    print(f"DocTypes: {dict(dt_dist.most_common())}")
    print(f"KW coverage: {len(kw_hits)}/{sum(len(v) for v in KW_GROUPS.values())}")
    print(f"Audit: {args.audit_output}")


if __name__ == "__main__":
    main()
