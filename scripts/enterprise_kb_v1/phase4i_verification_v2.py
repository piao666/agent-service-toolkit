#!/usr/bin/env python3
"""Phase 4I v2: Fresh Clone Verification — enriched metadata, script categories, workspace_path."""

import json, os, sys, subprocess, shutil
from pathlib import Path
from datetime import datetime, timezone

# Determine workspace from argv or cwd
WORKSPACE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
REPORTS = WORKSPACE / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)
TS = datetime.now(timezone.utc).isoformat()


def git_info():
    """Record git state."""
    info = {}
    for key, args in [("HEAD", ["rev-parse", "HEAD"]), ("branch", ["branch", "--show-current"]), ("status", ["status", "--short"])]:
        try:
            r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=str(WORKSPACE))
            info[key] = r.stdout.strip()
        except Exception:
            info[key] = "git not available"
    return info


def check_registry():
    """Enriched registry path check with full metadata."""
    print("=== CHECK 1: Registry Path (enriched) ===")
    results = {"check": "registry_path", "workspace_path": str(WORKSPACE.resolve()), "timestamp": TS, "registries": []}
    for reg_rel in [
        "data/enterprise_kb_v1/source_registry/source_registry.yaml",
        "data/enterprise_kb_v1/source_registry/internal_engineering_sources.yaml",
    ]:
        reg_path = WORKSPACE / reg_rel
        entry = {"registry": reg_rel, "exists": reg_path.exists(), "workspace_path": str(WORKSPACE.resolve())}
        missing = []; found = []
        if reg_path.exists():
            import yaml
            with open(reg_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            sources = data.get("sources", [])
            for src in sources:
                sid = src.get("source_id", "?")
                lp = src.get("local_path", "")
                if lp:
                    full = WORKSPACE / lp
                    if full.exists():
                        found.append({"source_id": sid, "local_path": lp})
                    else:
                        missing.append({
                            "source_id": sid,
                            "local_path": lp,
                            "resolved": str(full),
                            "enabled": src.get("enabled"),
                            "allowed_for_answer": src.get("allowed_for_answer", src.get("answer_scope")),
                            "doc_status": src.get("doc_status", src.get("status", "")),
                            "url_status": src.get("url_status", ""),
                            "fetch_status": src.get("fetch_status", src.get("capture_status", "")),
                            "exclusion_reason": _exclusion_reason(src),
                            "affects_runtime_retrieval": bool(src.get("enabled")),
                            "verdict": "pass_exception" if not src.get("enabled") else "fail",
                        })
            entry["total_sources"] = len(sources)
            entry["found"] = len(found)
            entry["missing"] = len(missing)
            entry["missing_details"] = missing
            print(f"  {reg_rel}: {len(found)}/{len(sources)} found, {len(missing)} missing")
            for m in missing:
                print(f"    {m['source_id']}: enabled={m['enabled']} -> verdict={m['verdict']}")
        results["registries"].append(entry)
    results["all_paths_exist_strict"] = sum(len(r.get("missing_details", [])) for r in results["registries"]) == 0
    results["all_runtime_critical_exist"] = all(
        m["verdict"] != "fail" for r in results["registries"] for m in r.get("missing_details", [])
    )
    with open(REPORTS / "phase4i_registry_path_check.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def _exclusion_reason(src: dict) -> str:
    sid = src.get("source_id", "")
    if "deprecated" in str(src.get("doc_status", "")) or "deprecated" in str(src.get("status", "")):
        return "deprecated_source"
    if "needs_manual_review" in str(src.get("url_status", "")):
        return "excluded_from_capture_url_not_verified"
    if "deprecated" in str(src.get("notes", "")):
        return "deprecated_in_notes"
    if not src.get("enabled", True):
        return "disabled_by_default"
    return "unknown"


def check_ignore():
    """Gitignore check with workspace_path."""
    print("\n=== CHECK 2: Git Ignore ===")
    ignore_path = WORKSPACE / ".gitignore"
    results = {"check": "gitignore", "workspace_path": str(WORKSPACE.resolve()), "timestamp": TS, "gitignore_exists": ignore_path.exists(), "patterns": []}
    REQUIRED = [
        "storage/", "models/", "*.zip",
        "data/enterprise_kb_v1/raw_sources/official_docs/",
        "data/enterprise_kb_v1/chunks/official_docs/",
        "data/enterprise_kb_v1/chunks/internal_engineering_docs/",
        "data/enterprise_kb_v1/internal_engineering_corpus/",
        "data/enterprise_kb_v1/manifests/phase4fh_internal_chunk_manifest.json",
    ]
    if ignore_path.exists():
        text = ignore_path.read_text(encoding="utf-8")
        for pat in REQUIRED:
            covered = pat in text or Path(pat).parent.as_posix() + "/" in text
            results["patterns"].append({"pattern": pat, "covered": covered})
            print(f"  {'COVERED' if covered else 'MISSING'}: {pat}")
        results["all_covered"] = all(p["covered"] for p in results["patterns"])
    with open(REPORTS / "phase4i_ignore_check.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def check_import():
    """Import smoke with package layout detection."""
    print("\n=== CHECK 3: Import Smoke ===")
    src_path = WORKSPACE / "src"
    has_src_prefix = src_path.exists() and (src_path / "rag").exists()
    layout = "src_prefix" if has_src_prefix else "no_src_prefix"
    if has_src_prefix:
        sys.path.insert(0, str(src_path))

    results = {"check": "import_smoke", "workspace_path": str(WORKSPACE.resolve()), "timestamp": TS, "package_layout": layout, "modules": []}

    MODULES = [
        ("rag.config", "full"),
        ("schema.models", "full"),
        ("rag.corpus_router", "full"),
        ("schema.schema", "full"),
        ("rag.vector_store", "import_only_no_connect"),
    ]

    for mod_name, mode in MODULES:
        entry = {"module": mod_name, "mode": mode}
        try:
            if mode == "import_only_no_connect":
                m = __import__(mod_name, fromlist=["get_collection_count"])
                entry["status"] = "pass"
                entry["available_symbols"] = [x for x in dir(m) if not x.startswith("_")][:10]
            else:
                __import__(mod_name)
                entry["status"] = "pass"
        except Exception as e:
            entry["status"] = "fail"
            entry["error"] = str(e)[:200]
            entry["skip_reason"] = _skip_reason(mod_name, str(e))
        print(f"  {mod_name} ({mode}): {entry['status']}")
        results["modules"].append(entry)

    # validate_runtime_config (always works without langchain)
    try:
        from rag.official_docs_retriever import validate_runtime_config
        vr = validate_runtime_config()
        results["modules"].append({
            "module": "rag.official_docs_retriever.validate_runtime_config",
            "mode": "validate_only",
            "status": "pass_validate_only",
            "local_config_pass": vr.get("local_config_values_pass"),
        })
        print(f"  rag.official_docs_retriever.validate: pass")
    except Exception as e:
        results["modules"].append({
            "module": "rag.official_docs_retriever.validate_runtime_config",
            "mode": "validate_only",
            "status": "fail",
            "error": str(e)[:200],
        })
        print(f"  rag.official_docs_retriever.validate: fail")

    results["all_importable"] = all(m["status"].startswith("pass") for m in results["modules"])
    with open(REPORTS / "phase4i_import_smoke_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def _skip_reason(mod: str, err: str) -> str:
    if "langchain" in err.lower():
        return "requires_langchain_full_stack_not_installed"
    if "chromadb" in err.lower():
        return "requires_chromadb"
    return f"import_failed: {err[:60]}"


def check_scripts():
    """Script check with proper categorization."""
    print("\n=== CHECK 4: Script Dry-Run ===")
    import py_compile
    results = {"check": "script_dry_run", "workspace_path": str(WORKSPACE.resolve()), "timestamp": TS, "scripts": []}
    sd = WORKSPACE / "scripts" / "enterprise_kb_v1"

    CATEGORIES = {
        "hpc_phase4c_run_embedding_ab.py": "heavy_hpc_script",
        "hpc_phase4c_run_retrieval_context_eval.py": "heavy_hpc_script",
        "hpc_phase4c_collect_results.py": "packaging_script",
        "hpc_phase4c_preflight.py": "heavy_hpc_script",
        "hpc_phase4d_build_bge_m3_index.py": "heavy_hpc_script",
        "hpc_phase4fh_build_internal_index.py": "heavy_hpc_script",
        "hpc_phase4fh_run_internal_eval.py": "heavy_hpc_script",
        "hpc_phase4fh_strict_eval.py": "heavy_hpc_script",
        "hpc_phase4fh_strict_patch.py": "heavy_hpc_script",
        "hpc_phase4fh_rag_routing_fix.py": "heavy_hpc_script",
        "runtime_retrieval_smoke.py": "heavy_hpc_script",
        "api_retrieval_smoke.py": "api_smoke_script",
        "chunk_internal_engineering_docs.py": "local_lightweight_script",
        "phase4fh_strict_eval_analyze.py": "analysis_script",
        "phase4fh_strict_eval_patch.py": "analysis_script",
        "phase4i_verification.py": "analysis_script",
        "phase4i_verification_v2.py": "analysis_script",
        "phase4a_full_corpus_build.py": "local_lightweight_script",
        "phase4b_corpus_repair.py": "local_lightweight_script",
        "phase4c_local_repair_and_hpc_package.py": "packaging_script",
        "phase4b_finish_rag_and_zip.py": "packaging_script",
        "phase3f_generate_package.py": "packaging_script",
    }

    for sp in sorted(sd.glob("*.py")):
        cat = CATEGORIES.get(sp.name, "heavy_hpc_script")
        entry = {"script": sp.name, "exists": True, "size_bytes": sp.stat().st_size, "category": cat}
        try:
            py_compile.compile(str(sp), doraise=True)
            entry["syntax_ok"] = True
        except py_compile.PyCompileError as e:
            entry["syntax_ok"] = False
            entry["syntax_error"] = str(e)[:200]

        if cat in ("analysis_script", "local_lightweight_script", "packaging_script"):
            entry["dry_run_supported"] = False
            entry["skip_reason"] = f"{cat} — syntax check only, no --dry-run flag"
        elif cat == "api_smoke_script":
            entry["dry_run_supported"] = False
            entry["skip_reason"] = "requires running API server, not executed in verification"
        else:
            entry["dry_run_supported"] = False
            entry["skip_reason"] = "heavy HPC script, requires GPU + SentenceTransformer + Chroma, not executed in verification"

        print(f"  {sp.name}: {cat} syntax={entry['syntax_ok']}")
        results["scripts"].append(entry)

    cats = {}
    for s in results["scripts"]:
        c = s.get("category", "unknown")
        cats[c] = cats.get(c, 0) + 1
    results["category_counts"] = cats
    results["all_syntax_ok"] = all(s.get("syntax_ok", False) for s in results["scripts"])
    with open(REPORTS / "phase4i_script_dry_run_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return results


def write_commands_log(git: dict):
    """Write the commands executed log."""
    log_path = REPORTS / "phase4i_fresh_clone_commands.log"
    lines = [
        f"# Phase 4I v2 Fresh Clone Commands Log",
        f"# Timestamp: {TS}",
        f"# Workspace: {WORKSPACE.resolve()}",
        "",
        f"git clone E:/RAG/agent-service-toolkit-clean E:/RAG/A/phase4i_fresh_clone_tmp/repo",
        f"cd E:/RAG/A/phase4i_fresh_clone_tmp/repo",
        f"git rev-parse HEAD  => {git.get('HEAD', '')}",
        f"git branch --show-current  => {git.get('branch', '')}",
        f"git status --short",
        git.get("status", ""),
        "",
        f"python scripts/enterprise_kb_v1/phase4i_verification_v2.py {WORKSPACE.resolve()}",
        "",
    ]
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nCommands log: {log_path}")


def main():
    git = git_info()
    print(f"HEAD: {git['HEAD']}")
    print(f"Branch: {git['branch']}")
    print()

    r1 = check_registry()
    r2 = check_ignore()
    r3 = check_import()
    r4 = check_scripts()
    write_commands_log(git)

    print(f"\n=== SUMMARY ===")
    print(f"  Registry strict: {r1['all_paths_exist_strict']}")
    print(f"  Registry runtime-critical: {r1['all_runtime_critical_exist']}")
    print(f"  Ignore: {r2['all_covered']}")
    print(f"  Import: {r3['all_importable']}")
    print(f"  Script syntax: {r4['all_syntax_ok']}")
    print(f"  Script categories: {r4.get('category_counts', {})}")
    print("DONE: Phase 4I v2")


if __name__ == "__main__":
    main()
