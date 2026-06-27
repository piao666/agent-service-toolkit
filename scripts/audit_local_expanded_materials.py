"""只读审计本地新增资料目录，不构建 Chroma。"""
import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "knowledge_base" / "evaluation"

EXCLUDE_DIRS = {".venv", ".idea", ".ipynb_checkpoints", "__pycache__", ".git",
                "models", "checkpoints", "outputs", "logs", "node_modules"}
EXCLUDE_EXTENSIONS = {".pth", ".pt", ".bin", ".safetensors", ".h5", ".onnx",
                      ".ckpt", ".tar", ".gz", ".zip", ".rar", ".7z"}
SENSITIVE_PATTERNS = ["api_key", "secret", "token", "password", "sk-", "AKIA",
                      ".env", "credentials", "private"]

# Source_id mapping rules
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

ML_DIR_SOURCE_MAP = {
    "Bayes": "local_machine_learning_course",
    "KMeans": "local_machine_learning_course",
    "KNN": "local_machine_learning_course",
    "Linear Regression": "local_machine_learning_course",
    "Logistic Regression": "local_machine_learning_course",
    "SVM": "local_machine_learning_course",
    "Tree": "local_machine_learning_course",
    "集成": "local_machine_learning_course",
}

DOMAIN_MAP = {
    "local_langchain_course_pdf": "langchain_agent",
    "local_llm_course_pptx": "llm_course",
    "local_python_llm_course_docx": "python_llm",
    "local_data_analysis_llm_notes_docx": "data_analysis",
    "local_machine_learning_course": "machine_learning",
    "local_machine_learning_course_docx": "machine_learning",
    "local_math_foundation_docx": "math_foundation",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--roots", nargs="+", default=[
        r"E:\Python\sgg-data", r"E:\Python\Machine Learning"
    ])
    p.add_argument("--output", default=str(EVAL_DIR / "local_expanded_materials_audit.json"))
    p.add_argument("--file-list-output", default=str(EVAL_DIR / "local_expanded_materials_file_list.json"))
    return p.parse_args()


def _resolve_source_id(file_path: Path, root: Path) -> str:
    """根据文件路径和 root 决定 source_id。"""
    fname = file_path.name
    rel = str(file_path.relative_to(root))

    if "sgg-data" in str(root).lower():
        for prefix, sid in SGG_SOURCE_MAP.items():
            if fname.startswith(prefix):
                return sid
        return f"local_sgg_{file_path.suffix.lstrip('.')}"

    if "Machine Learning" in str(root):
        for prefix, sid in ML_SOURCE_MAP.items():
            if fname.startswith(prefix):
                return sid
        # Check parent directory name
        parent = file_path.parent.name
        if parent in ML_DIR_SOURCE_MAP:
            return ML_DIR_SOURCE_MAP[parent]
        return f"local_ml_{file_path.suffix.lstrip('.')}"

    return file_path.stem


def _resolve_domain(source_id: str) -> str:
    return DOMAIN_MAP.get(source_id, "unknown")


def _check_sensitive(file_path: Path) -> tuple[bool, str]:
    """检查文件是否包含敏感内容。"""
    fname = file_path.name.lower()
    for pat in SENSITIVE_PATTERNS:
        if pat.lower() in fname:
            return True, f"sensitive_filename:{pat}"
    # Quick scan of small text files
    if file_path.suffix.lower() in {".txt", ".md", ".py", ".env", ".json", ".yaml", ".yml"}:
        try:
            if file_path.stat().st_size < 50_000:
                content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
                for pat in SENSITIVE_PATTERNS:
                    if pat.lower() in content:
                        return True, f"sensitive_content:{pat}"
        except Exception:
            pass
    return False, ""


def _should_skip_dir(dir_path: Path) -> bool:
    return dir_path.name in EXCLUDE_DIRS or dir_path.name.startswith(".")


def _should_skip_file(file_path: Path) -> tuple[bool, str]:
    ext = file_path.suffix.lower()
    if ext in EXCLUDE_EXTENSIONS:
        return True, f"excluded_extension:{ext}"
    if file_path.stat().st_size > 200_000_000:  # 200MB+
        return True, "file_too_large"
    return False, ""


def main() -> None:
    args = _parse_args()
    now = datetime.now(DATETIME_UTC).isoformat()

    all_files = []
    skipped = []
    ext_counter = Counter()
    sid_counter = Counter()
    domain_counter = Counter()
    sensitive_found = []
    dir_stats: dict[str, dict] = {}

    for root_str in args.roots:
        root = Path(root_str)
        if not root.exists():
            print(f"[WARN] Root not found: {root}")
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(Path(dirpath) / d)]

            for fname in filenames:
                fp = Path(dirpath) / fname
                skip, reason = _should_skip_file(fp)
                is_sensitive, sens_reason = _check_sensitive(fp)
                if is_sensitive:
                    sensitive_found.append({"path": str(fp), "reason": sens_reason})

                ext = fp.suffix.lower() or ".noext"
                ext_counter[ext] += 1

                source_id = _resolve_source_id(fp, root)
                domain = _resolve_domain(source_id)

                if skip:
                    skipped.append({
                        "path": str(fp), "reason": reason,
                        "source_id": source_id, "extension": ext,
                    })
                    continue

                # Ingestible file types
                supported = {".pdf", ".docx", ".pptx", ".ipynb", ".py", ".md", ".txt", ".csv"}
                ingestible = ext in supported

                sid_counter[source_id] += 1
                domain_counter[domain] += 1

                st = fp.stat()
                all_files.append({
                    "absolute_path": str(fp),
                    "relative_path": str(fp.relative_to(root)),
                    "root": root_str,
                    "file_name": fname,
                    "extension": ext,
                    "size_bytes": st.st_size,
                    "modified_time": datetime.fromtimestamp(st.st_mtime, tz=DATETIME_UTC).isoformat(),
                    "proposed_source_id": source_id,
                    "proposed_doc_type": ext.lstrip(".") if ext != ".noext" else "unknown",
                    "proposed_domain": domain,
                    "ingest_candidate": ingestible,
                    "skip_reason": reason if skip else "",
                })

    # ── Directory stats ──
    for root_str in args.roots:
        root = Path(root_str)
        if not root.exists():
            continue
        rfiles = [f for f in all_files if f["root"] == root_str]
        rskipped = [s for s in skipped if root_str in s["path"]]
        ext_dist = Counter(f["extension"] for f in rfiles)
        dir_stats[root_str] = {
            "total_files": len(rfiles),
            "skipped_files": len(rskipped),
            "extension_distribution": dict(ext_dist.most_common()),
            "source_id_distribution": dict(Counter(f["proposed_source_id"] for f in rfiles).most_common()),
        }

    # ── Output ──
    file_list = {
        "generated_at": now,
        "roots": args.roots,
        "total_files": len(all_files),
        "total_skipped": len(skipped),
        "skipped_files": skipped,
        "files": all_files,
    }
    Path(args.file_list_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.file_list_output).write_text(json.dumps(file_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = {
        "generated_at": now,
        "roots": args.roots,
        "total_files": len(all_files),
        "total_skipped": len(skipped),
        "extension_distribution": dict(ext_counter.most_common()),
        "source_id_distribution": dict(sid_counter.most_common()),
        "domain_distribution": dict(domain_counter.most_common()),
        "estimated_new_source_ids": len(sid_counter),
        "ingestible_files": sum(1 for f in all_files if f["ingest_candidate"]),
        "non_ingestible_files": sum(1 for f in all_files if not f["ingest_candidate"]),
        "sensitive_found": len(sensitive_found) > 0,
        "sensitive_details": sensitive_found[:10] if sensitive_found else [],
        "excluded_dirs_found": [],
        "directory_stats": dir_stats,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Print
    print(f"Roots: {args.roots}")
    print(f"Files: {len(all_files)} total, {len(skipped)} skipped")
    print(f"Ingestible: {audit['ingestible_files']}")
    print(f"Extensions: {dict(ext_counter.most_common(10))}")
    print(f"Source IDs: {dict(sid_counter.most_common())}")
    print(f"Sensitive found: {audit['sensitive_found']}")
    if sensitive_found:
        for s in sensitive_found[:3]:
            print(f"  {s['path']}: {s['reason']}")
    print(f"\nOutput: {args.output}")
    print(f"File list: {args.file_list_output}")


if __name__ == "__main__":
    main()
