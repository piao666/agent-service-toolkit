"""审计本项目中存在的 Chroma 向量库集合。

列出每个库的 collection 名称、chunk 数量、source_id 分布等信息。
不修改任何 Chroma 数据，不加载 embedding 模型，不调用 LLM。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

try:
    import chromadb  # noqa: E402
except ImportError:
    print("chromadb 未安装，请先安装: pip install chromadb", file=sys.stderr)
    sys.exit(1)


# 已知可能存在的 Chroma 目录及其 collection
KNOWN_DIRS = [
    {
        "label": "小型库 (Phase 1)",
        "persist_dir": "chroma_enterprise",
        "collection_name": "enterprise_knowledge_base",
    },
    {
        "label": "Phase6 技术资料库",
        "persist_dir": "chroma_enterprise_phase6",
        "collection_name": "enterprise_ai_learning_kb_reviewed",
    },
    {
        "label": "最终合并库",
        "persist_dir": "chroma_enterprise_final",
        "collection_name": "enterprise_knowledge_base",
    },
]

DEFAULT_OUTPUT_PATH = (
    ROOT_DIR / "data" / "knowledge_base" / "evaluation" / "final_chroma_index_audit.json"
)


def _safe_collection_info(
    persist_dir: str, collection_name: str
) -> dict[str, Any] | None:
    """安全获取 collection 信息，不存在时返回 None。"""
    resolved = ROOT_DIR / persist_dir
    if not resolved.exists():
        return None

    try:
        client = chromadb.PersistentClient(path=str(resolved))
        coll = client.get_collection(collection_name)
    except Exception as exc:
        return {
            "persist_dir": persist_dir,
            "collection_name": collection_name,
            "exists": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    count = coll.count()
    info: dict[str, Any] = {
        "persist_dir": persist_dir,
        "collection_name": collection_name,
        "exists": True,
        "count": count,
    }

    if count == 0:
        info["source_ids"] = []
        info["source_id_distribution"] = {}
        info["metadata_keys_sample"] = []
        return info

    # 获取全部 metadata（collection 规模可控，直接全量读取）
    try:
        result = coll.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
    except Exception as exc:
        info["metadata_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return info

    # source_id 分布
    sid_counter: Counter = Counter()
    all_keys: set[str] = set()
    for meta in metadatas:
        if isinstance(meta, dict):
            sid = meta.get("source_id") or meta.get("source") or "unknown"
            sid_counter[sid] += 1
            all_keys.update(meta.keys())

    info["source_id_distribution"] = dict(sid_counter.most_common())
    info["unique_source_count"] = len(sid_counter)
    info["metadata_keys"] = sorted(all_keys)

    # 抽样展示前 3 条 metadata
    samples: list[dict[str, Any]] = []
    for meta in metadatas[:3]:
        if isinstance(meta, dict):
            samples.append({k: str(v)[:120] for k, v in meta.items()})
    info["metadata_samples"] = samples

    # 关键文档覆盖检查（子串匹配，兼容 source_id 和 source 两种 schema）
    key_docs = ["fastapi_docs", "enterprise_rag_pipeline", "enterprise_agent_overview"]
    all_sids_str = " ".join(sid_counter.keys())
    info["key_document_coverage"] = {
        doc: doc in all_sids_str for doc in key_docs
    }

    return info


def audit_all(output_path: str | Path | None = None) -> dict[str, Any]:
    """审计所有已知 Chroma 库并生成报告。"""
    results: list[dict[str, Any]] = []
    for entry in KNOWN_DIRS:
        info = _safe_collection_info(entry["persist_dir"], entry["collection_name"])
        if info:
            info["label"] = entry["label"]
            results.append(info)

    now = datetime.now(DATETIME_UTC).isoformat()
    report: dict[str, Any] = {
        "generated_at": now,
        "total_collections_checked": len(KNOWN_DIRS),
        "collections_found": sum(1 for r in results if r.get("exists")),
        "collections": results,
        "calls_llm": False,
        "writes_chroma": False,
        "writes_embeddings": False,
    }

    # 写入 JSON
    resolved_output = Path(output_path or DEFAULT_OUTPUT_PATH)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="审计本项目中存在的 Chroma 向量库集合。"
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"输出 JSON 路径 (默认: {DEFAULT_OUTPUT_PATH})",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = audit_all(output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
