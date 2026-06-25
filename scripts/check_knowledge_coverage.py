#!/usr/bin/env python3
"""Knowledge base coverage checker — read-only scan, no LLM, no Chroma write."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = REPO_ROOT / "data" / "knowledge_base"
EVAL_DIR = REPO_ROOT / "data" / "knowledge_base" / "evaluation"
DOCS_DIR = REPO_ROOT / "docs" / "enterprise_rag_backend"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
TEXT_EXTS = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".html", ".xml"}
KEYWORDS = [
    "FastAPI", "Request Body", "Pydantic", "LoRA", "RAG", "LangGraph",
    "Chroma", "embedding", "DeepSeek", "Qwen", "Agent", "Python",
    "机器学习", "深度学习", "NLP", "Transformer", "Attention",
    "反向传播", "微调", "推理", "知识库", "检索", "分块",
    "chunk", "manifest", "normalize", "evaluation", "source_id",
    "Streamlit", "depends", "dependency", "middleware", "router",
]
PREVIEW_LEN = 160


def _safe_preview(text: str) -> str:
    clean = text.replace("\n", " ").replace("\r", " ")[:PREVIEW_LEN]
    # redact any secret-like patterns
    import re
    clean = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", clean)
    clean = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.-]+", "Bearer [REDACTED]", clean)
    return clean.strip()


def scan_files(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_SIZE:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        files.append({
            "relpath": str(path.relative_to(REPO_ROOT)),
            "text": text.lower(),
            "size": size,
        })
    return files


def main():
    print(f"Scanning {KB_ROOT} …")
    files = scan_files(KB_ROOT)
    print(f"Scanned {len(files)} text files")

    # Also scan scripts for project keywords (optional)
    scripts_root = REPO_ROOT / "scripts"
    if scripts_root.exists():
        script_files = scan_files(scripts_root)
        files.extend(script_files)
        print(f"+ {len(script_files)} script files")

    results: dict[str, dict[str, Any]] = {}
    for kw in KEYWORDS:
        kw_lower = kw.lower()
        hits: list[dict[str, Any]] = []
        for f in files:
            count = f["text"].count(kw_lower)
            if count > 0:
                hits.append({"relpath": f["relpath"], "count": count})
        top_files = sorted(hits, key=lambda x: x["count"], reverse=True)[:5]
        total_hits = sum(h["count"] for h in hits)
        results[kw] = {
            "keyword": kw,
            "file_count": len(hits),
            "hit_count": total_hits,
            "top_files": [h["relpath"] for h in top_files],
            "likely_covered": total_hits >= 3 or len(hits) >= 2,
        }

    # Write JSON report
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    report_path = EVAL_DIR / "knowledge_coverage_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write MD report
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = DOCS_DIR / "KNOWLEDGE_COVERAGE_CHECK.md"
    lines = [
        "# 知识库覆盖排查报告",
        "",
        "## 检查范围",
        f"- 知识库目录: `data/knowledge_base/`",
        f"- 扫描文件数: {len(files)}",
        f"- 关键词数: {len(KEYWORDS)}",
        "- 限制: 每文件 ≤5MB，仅文本格式 (md/txt/json/jsonl/yaml/csv/html)",
        "",
        "## 关键词覆盖概览",
        "",
        "| 关键词 | 文件数 | 命中数 | 是否覆盖 |",
        "|--------|--------|--------|----------|",
    ]
    for kw in KEYWORDS:
        r = results[kw]
        cov = "COVERED" if r["likely_covered"] else "GAP"
        lines.append(f"| {kw} | {r['file_count']} | {r['hit_count']} | {cov} |")

    lines += [
        "",
        "## 重点结论",
        "",
    ]
    # FastAPI / Request Body / LoRA analysis
    for kw in ["FastAPI", "Request Body", "LoRA"]:
        r = results[kw]
        if not r["likely_covered"]:
            lines.append(f"- **{kw}**: 覆盖不足 (文件数={r['file_count']}, 命中={r['hit_count']})。如果 demo 中相关回答缺少来源支持，主要是知识库覆盖不足，不应归因于 Agent 编排失败。")
        else:
            lines.append(f"- **{kw}**: 基本覆盖 (文件数={r['file_count']}, 命中={r['hit_count']})。")

    # RAG / Agent / Chroma analysis
    for kw in ["RAG", "Agent", "Chroma"]:
        r = results[kw]
        if r["likely_covered"]:
            lines.append(f"- **{kw}**: 覆盖较好 (文件数={r['file_count']}, 命中={r['hit_count']})，说明系统项目类问题覆盖较好。")
        else:
            lines.append(f"- **{kw}**: 覆盖不足 (文件数={r['file_count']}, 命中={r['hit_count']})。")

    lines += [
        "",
        "## 判断",
        "",
        "如果 FastAPI / Request Body / Pydantic / LoRA 等命中很少或为 0，",
        "则回答缺少来源支持主要是知识库覆盖不足，而非检索或 Agent 编排失败。",
        "",
        "如果 RAG / Agent / Chroma 等命中较多，说明系统项目类问题覆盖较好。",
        "",
        "## 后续建议",
        "",
        "1. 补充 FastAPI / Request Body / Pydantic 相关知识库资料。",
        "2. 补充 LoRA / 微调 / QLoRA 相关中文资料。",
        "3. 补充 DeepSeek / Qwen 等模型调用方式资料。",
        "4. 考虑添加 corpus expansion 流程。",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Print summary
    print("\n=== Coverage Summary ===")
    for kw in KEYWORDS:
        r = results[kw]
        flag = "COVERED" if r["likely_covered"] else "GAP"
        print(f"  {flag} {kw:20s}: files={r['file_count']:2d} hits={r['hit_count']:4d}")
    print(f"\nReport: {report_path}")
    print(f"Report: {md_path}")


if __name__ == "__main__":
    main()
