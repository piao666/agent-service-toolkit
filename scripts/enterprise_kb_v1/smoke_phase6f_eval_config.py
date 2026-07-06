#!/usr/bin/env python3
"""Phase 6F 本地 Config Smoke v1.1 — 只检查配置/逻辑，不加载 embedding/Chroma。

验证:
  1. cases 文件可读且格式正确，case count 统计准确
  2. HPC 脚本语法通过
  3. 核心逻辑：索引缺失策略 (任一缺失 → fatal)
  4. 核心逻辑：citation empty candidates 不默认 valid
  5. 核心逻辑：route metric 区分 gold execution vs classifier prediction
  6. 输出路径可创建
  7. 无 heavy import
"""

import json, sys, re
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
PROJECT = Path(__file__).resolve().parent.parent.parent
REPORTS = PROJECT / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)


def test_cases_readable():
    path = PROJECT / "data" / "enterprise_kb_v1" / "eval" / "phase6f_multichannel_retrieval_cases.jsonl"
    if not path.exists():
        return {"pass": False, "error": f"cases file not found: {path}"}

    cases = []
    errors = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
                for field in ["case_id", "query", "expected_route_mode", "expected_target_corpora", "case_type"]:
                    if field not in case:
                        errors.append(f"line {i}: missing '{field}'")
                cases.append(case)
            except json.JSONDecodeError as e:
                errors.append(f"line {i}: invalid JSON: {e}")

    # 统计
    case_type_counts = {}
    route_mode_counts = {}
    for c in cases:
        ct = c.get("case_type", "?")
        rm = c.get("expected_route_mode", "?")
        case_type_counts[ct] = case_type_counts.get(ct, 0) + 1
        route_mode_counts[rm] = route_mode_counts.get(rm, 0) + 1

    total = len(cases)

    return {
        "pass": len(errors) == 0 and total > 0,
        "case_count": total,
        "format_errors": errors,
        "case_type_distribution": case_type_counts,
        "route_mode_distribution": route_mode_counts,
        "has_official_only": route_mode_counts.get("official_only", 0) > 0,
        "has_internal_only": route_mode_counts.get("internal_only", 0) > 0,
        "has_dual": route_mode_counts.get("dual", 0) > 0,
        "has_no_hit": any(c.get("case_type") == "no_hit" for c in cases),
        "has_keyword_exact": any(c.get("case_type") == "keyword_exact" for c in cases),
        "has_metadata_filter": any(c.get("case_type") == "metadata_filter" for c in cases),
        "has_history_aware": any(c.get("case_type") == "history_aware" for c in cases),
    }


def test_script_syntax():
    path = PROJECT / "scripts" / "enterprise_kb_v1" / "run_phase6f_multichannel_retrieval_eval.py"
    if not path.exists():
        return {"pass": False, "error": f"script not found: {path}"}

    import py_compile
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as e:
        return {"pass": False, "error": str(e)[:200]}

    # 额外逻辑检查：读取源码验证关键语义
    source = path.read_text(encoding="utf-8")

    # 检查 1: 索引缺失策略 — 任一缺失 fatal
    has_either_fatal = (
        "index_missing" in source
        and "sys.exit(1)" in source
        and "missing_indices" in source
    )

    # 检查 2: citation empty 不默认 valid
    has_citation_logic = (
        "no_candidates_with_hits" in source
        and "not_applicable" in source
    )

    # 检查 3: route metric 区分语义
    has_route_semantic = (
        "route_execution_accuracy_given_gold_route" in source
        or "route_metric_note" in source
    )

    # 检查 4: overall_pass gates
    has_gates = "indices_ready" in source and "citation_ok" in source

    logic_checks = {
        "index_either_missing_fatal": has_either_fatal,
        "citation_empty_not_default_valid": has_citation_logic,
        "route_metric_semantic_clear": has_route_semantic,
        "overall_pass_has_gates": has_gates,
    }
    all_logic_ok = all(logic_checks.values())

    return {
        "pass": all_logic_ok,
        "script": str(path.name),
        "logic_checks": logic_checks,
    }


def test_output_paths():
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        test_file = REPORTS / ".phase6f_smoke_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return {"pass": True}
    except Exception as e:
        return {"pass": False, "error": str(e)[:200]}


def test_no_heavy_imports():
    banned = ["sentence_transformers", "chromadb", "torch"]
    imported = [mod for mod in banned if mod in sys.modules]
    return {"pass": len(imported) == 0, "imported_heavy_modules": imported}


def main():
    print("=== Phase 6F Config Smoke v1.1 ===")
    results = {"smoke": "phase6f_eval_config", "timestamp": datetime.now(timezone.utc).isoformat()}

    tests = [
        ("cases_readable", test_cases_readable()),
        ("script_syntax", test_script_syntax()),
        ("output_paths", test_output_paths()),
        ("no_heavy_imports", test_no_heavy_imports()),
    ]

    for name, r in tests:
        status = "PASS" if r["pass"] else "FAIL"
        extra = ""
        if name == "cases_readable":
            extra = f" ({r.get('case_count','?')} cases, types={r.get('case_type_distribution',{})})"
        elif name == "script_syntax":
            extra = f" logic={r.get('logic_checks',{})}"
        print(f"  {name}: {status}{extra}")
        if not r["pass"]:
            print(f"    -> {r.get('error', r.get('format_errors', '?'))}")
        results[name] = r

    all_pass = all(r["pass"] for _, r in tests)
    results["overall_pass"] = all_pass

    path = REPORTS / "phase6f_eval_config_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")

    if not all_pass:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
