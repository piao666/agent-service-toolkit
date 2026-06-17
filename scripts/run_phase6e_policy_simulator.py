from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rag.retrieval_policy import (  # noqa: E402
    QueryType,
    RetrievalPolicyName,
    citation_evidence_check,
    decide_gated_retrieval_policy,
    infer_query_type,
    metadata_first_score,
    select_retrieval_policy,
    sparse_first_score,
    split_multi_hop_query,
)

EVALUATION_DIR = ROOT / "data" / "knowledge_base" / "evaluation"
DEFAULT_RESULTS_PATH = EVALUATION_DIR / "phase6e_policy_simulation_results.jsonl"
DEFAULT_CASES_PATH = EVALUATION_DIR / "phase6e_remaining_bad_cases.jsonl"
DEFAULT_SUMMARY_PATH = EVALUATION_DIR / "phase6e_policy_simulation_summary.json"
DEFAULT_PHASE6E5_PROBE_RESULTS_PATH = (
    EVALUATION_DIR / "phase6e5_local_policy_probe_results.jsonl"
)
DEFAULT_PHASE6E5_PROBE_SUMMARY_PATH = EVALUATION_DIR / "phase6e5_local_policy_probe_summary.json"
DEFAULT_PHASE6E7_PROBE_RESULTS_PATH = (
    EVALUATION_DIR / "phase6e7_gated_policy_probe_results.jsonl"
)
DEFAULT_PHASE6E7_PROBE_SUMMARY_PATH = EVALUATION_DIR / "phase6e7_gated_policy_probe_summary.json"
DEFAULT_PHASE6E9_PROBE_RESULTS_PATH = (
    EVALUATION_DIR / "phase6e9_conservative_gate_probe_results.jsonl"
)
DEFAULT_PHASE6E9_PROBE_SUMMARY_PATH = (
    EVALUATION_DIR / "phase6e9_conservative_gate_probe_summary.json"
)

FINAL_POLICY_DISTRIBUTION = {
    QueryType.EXACT_METADATA_LOOKUP.value: 31,
    QueryType.PHASE6C_BAD_CASE_REGRESSION.value: 10,
    QueryType.CODE_API_CONFIG.value: 7,
    QueryType.AMBIGUOUS_QUERY.value: 6,
    QueryType.CITATION_REQUIRED_QUERY.value: 5,
}

PREFERRED_INPUTS = {
    "agent_results": "phase6d9_deepseek_agent_api_results.jsonl",
    "calibrated_summary": "phase6d9_deepseek_calibrated_summary.json",
    "calibrated_taxonomy": "phase6d9_deepseek_calibrated_bad_taxonomy.jsonl",
    "raw_taxonomy": "phase6d9_deepseek_raw_bad_taxonomy.jsonl",
    "expanded_cases": "phase6d7_expanded_cases.jsonl",
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def discover_inputs(evaluation_dir: Path) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for key, filename in PREFERRED_INPUTS.items():
        path = evaluation_dir / filename
        if path.exists():
            discovered[key] = path

    if "calibrated_taxonomy" not in discovered:
        matches = sorted(evaluation_dir.glob("phase6d9*calibrated*bad*taxonomy*.jsonl"))
        if matches:
            discovered["calibrated_taxonomy"] = matches[0]
    if "agent_results" not in discovered:
        matches = sorted(evaluation_dir.glob("phase6d9*agent*results*.jsonl"))
        if matches:
            discovered["agent_results"] = matches[0]
    if "expanded_cases" not in discovered:
        matches = sorted(evaluation_dir.glob("phase6d7*expanded*cases*.jsonl"))
        if matches:
            discovered["expanded_cases"] = matches[0]
    return discovered


def indexed_by_case(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("case_id")): row for row in rows if row.get("case_id")}


def merge_case_rows(
    taxonomy_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    expanded_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results_by_id = indexed_by_case(result_rows)
    expanded_by_id = indexed_by_case(expanded_rows)
    merged: list[dict[str, Any]] = []
    for row in taxonomy_rows:
        case_id = str(row.get("case_id"))
        expanded = expanded_by_id.get(case_id, {})
        result = results_by_id.get(case_id, {})
        original_query_type = row.get("query_type") or expanded.get("query_type") or result.get(
            "query_type"
        )
        merged.append(
            {
                **expanded,
                **result,
                **row,
                "case_id": case_id,
                "query": row.get("query") or expanded.get("query") or result.get("query") or "",
                "original_query_type": original_query_type,
                "original_bad_reason": row.get("failure_type") or result.get("error_type"),
            }
        )
    return merged


def exact_metadata_candidate_score(row: dict[str, Any]) -> int:
    query = str(row.get("query") or "").lower()
    score = 0
    metadata_terms = (
        "source_id",
        "doc_type",
        "domain",
        "title",
        "section_path",
        "chunk_id",
        "source_url",
        "normalized_id",
        "collection_name",
        "review_status",
        "ingest_candidate",
    )
    score += sum(2 for term in metadata_terms if term in query)
    if row.get("requires_exact_match"):
        score += 3
    if row.get("failure_type") == "exact_metadata_retrieval_fail":
        score += 4
    if row.get("expected_source_id") and not row.get("source_hit", True):
        score += 1
    return score


def code_candidate_score(row: dict[str, Any]) -> int:
    query = str(row.get("query") or "")
    score = 0
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*(?:\(|=|:|/)", query):
        score += 3
    score += sum(
        1
        for term in ("api", "config", "function", "class", "path", "参数", "配置", "报错")
        if term.lower() in query.lower()
    )
    return score


def choose_cases_for_policy(
    candidates: list[dict[str, Any]],
    target_type: str,
    target_count: int,
    selected_ids: set[str],
) -> list[dict[str, Any]]:
    available = [row for row in candidates if row["case_id"] not in selected_ids]

    def primary(row: dict[str, Any]) -> bool:
        return row.get("original_query_type") == target_type

    if target_type == QueryType.EXACT_METADATA_LOOKUP.value:
        ranked = sorted(
            available,
            key=lambda row: (
                primary(row),
                exact_metadata_candidate_score(row),
                row.get("case_id", ""),
            ),
            reverse=True,
        )
    elif target_type == QueryType.CODE_API_CONFIG.value:
        ranked = sorted(
            available,
            key=lambda row: (primary(row), code_candidate_score(row), row.get("case_id", "")),
            reverse=True,
        )
    else:
        ranked = sorted(
            available,
            key=lambda row: (primary(row), row.get("case_id", "")),
            reverse=True,
        )

    chosen: list[dict[str, Any]] = []
    for row in ranked:
        if len(chosen) >= target_count:
            break
        if primary(row) or target_type == QueryType.EXACT_METADATA_LOOKUP.value:
            chosen.append(row)
        elif target_type == QueryType.CODE_API_CONFIG.value and code_candidate_score(row) > 0:
            chosen.append(row)
        elif target_type in {
            QueryType.PHASE6C_BAD_CASE_REGRESSION.value,
            QueryType.AMBIGUOUS_QUERY.value,
            QueryType.CITATION_REQUIRED_QUERY.value,
        }:
            chosen.append(row)
    return chosen


def build_remaining_bad_cases(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_ids: set[str] = set()
    remaining: list[dict[str, Any]] = []

    selection_order = (
        QueryType.PHASE6C_BAD_CASE_REGRESSION.value,
        QueryType.CODE_API_CONFIG.value,
        QueryType.AMBIGUOUS_QUERY.value,
        QueryType.CITATION_REQUIRED_QUERY.value,
        QueryType.EXACT_METADATA_LOOKUP.value,
    )
    for policy_type in selection_order:
        target_count = FINAL_POLICY_DISTRIBUTION[policy_type]
        chosen = choose_cases_for_policy(candidates, policy_type, target_count, selected_ids)
        for row in chosen:
            selected_ids.add(row["case_id"])
            derivation = (
                "original_query_type"
                if row.get("original_query_type") == policy_type
                else "policy_cluster_reassignment"
            )
            remaining.append(
                {
                    "case_id": row["case_id"],
                    "query": row.get("query") or "",
                    "query_type": policy_type,
                    "original_query_type": row.get("original_query_type"),
                    "original_bad_reason": row.get("original_bad_reason"),
                    "policy_case_derivation": derivation,
                    "expected_source_id": row.get("expected_source_id"),
                    "expected_doc_type": row.get("expected_doc_type"),
                    "expected_keywords": row.get("expected_keywords") or [],
                    "expected_exact_terms": row.get("expected_exact_terms") or [],
                    "source_hit": bool(row.get("source_hit")),
                    "keyword_hit": bool(row.get("keyword_hit")),
                    "doc_type_hit": bool(row.get("doc_type_hit")),
                    "banned_source_returned": bool(row.get("banned_source_returned")),
                    "returned_source_ids": row.get("returned_source_ids") or [],
                    "source_count": row.get("source_count"),
                    "evidence_present": row.get("evidence_present"),
                    "citations_present": row.get("citations_present"),
                }
            )

    if len(remaining) != sum(FINAL_POLICY_DISTRIBUTION.values()):
        raise RuntimeError(
            "Unable to build the requested Phase 6E regression suite from available artifacts."
        )
    return remaining


def simulate_case(row: dict[str, Any]) -> dict[str, Any]:
    query_type = infer_query_type(row.get("query", ""), {"query_type": row.get("query_type")})
    policy = select_retrieval_policy(query_type)
    query = row.get("query") or ""
    expected_source = row.get("expected_source_id")
    expected_keywords = row.get("expected_keywords") or []
    exact_terms = row.get("expected_exact_terms") or []
    notes: list[str] = []
    simulated_source_hit = False
    simulated_keyword_hit = False
    simulation_status = "design_only"

    if policy.name is RetrievalPolicyName.METADATA_FIRST:
        metadata = {
            "source_id": expected_source,
            "doc_type": row.get("expected_doc_type"),
            "chunk_id": " ".join(str(term) for term in exact_terms),
        }
        score = metadata_first_score(query, metadata)
        simulated_source_hit = bool(expected_source and (score > 0 or exact_terms))
        simulation_status = "offline_rule_estimate" if simulated_source_hit else "design_only"
        notes.append(f"metadata_first_score={score:.2f}")
    elif policy.name is RetrievalPolicyName.SPARSE_FIRST_BM25:
        expected_text = " ".join(str(keyword) for keyword in [*expected_keywords, *exact_terms])
        sparse_score = sparse_first_score(query, expected_text)
        simulated_keyword_hit = sparse_score > 0 or bool(row.get("keyword_hit"))
        simulation_status = "offline_rule_estimate" if simulated_keyword_hit else "design_only"
        notes.append(f"sparse_first_score={sparse_score:.2f}")
    elif policy.name is RetrievalPolicyName.CLARIFICATION_FIRST:
        notes.extend(("clarification_first", "multi_candidate_answer", "do_not_force_single_source"))
    elif policy.name is RetrievalPolicyName.CITATION_AWARE_EVIDENCE:
        source = {
            "metadata": {"source_id": expected_source, "title": row.get("expected_doc_type")},
            "content_preview": " ".join(str(keyword) for keyword in expected_keywords),
        }
        citation_check = citation_evidence_check(query, source)
        simulated_source_hit = bool(citation_check["citation_ready"])
        simulated_keyword_hit = bool(citation_check["keyword_overlap"] or row.get("keyword_hit"))
        simulation_status = "offline_rule_estimate" if simulated_source_hit else "design_only"
        notes.append(f"citation_ready={citation_check['citation_ready']}")
    elif policy.name is RetrievalPolicyName.MULTI_QUERY_RETRIEVAL:
        subqueries = split_multi_hop_query(query)
        simulation_status = "offline_rule_estimate" if len(subqueries) > 1 else "design_only"
        notes.append(f"subquery_count={len(subqueries)}")
    elif policy.name is RetrievalPolicyName.BANNED_SOURCE_GUARD_FIRST:
        simulation_status = "offline_rule_estimate"
        notes.append("banned-source success is guard-based, not source-hit-based")
    else:
        simulated_source_hit = bool(row.get("source_hit"))
        simulated_keyword_hit = bool(row.get("keyword_hit"))
        simulation_status = "baseline_reference"

    expected_improvement_reason = {
        RetrievalPolicyName.METADATA_FIRST: "Metadata fields can be matched before dense scoring.",
        RetrievalPolicyName.SPARSE_FIRST_BM25: "Exact symbols and config terms should be lexical-first.",
        RetrievalPolicyName.DENSE_SPARSE_FUSION: "Combines semantic recall with keyword coverage.",
        RetrievalPolicyName.CLARIFICATION_FIRST: "Avoids penalizing inherently ambiguous queries as retrieval misses.",
        RetrievalPolicyName.MULTI_QUERY_RETRIEVAL: "Rule-based subqueries can recover multi-hop evidence.",
        RetrievalPolicyName.CITATION_AWARE_EVIDENCE: "Evidence verifier can reject untraceable sources.",
        RetrievalPolicyName.BANNED_SOURCE_GUARD_FIRST: "Banned sources are filtered before scoring.",
    }[policy.name]

    return {
        "case_id": row["case_id"],
        "query": query,
        "query_type": row.get("query_type"),
        "original_query_type": row.get("original_query_type"),
        "original_bad_reason": row.get("original_bad_reason"),
        "recommended_policy": policy.name.value,
        "simulation_status": simulation_status,
        "simulated_source_hit": simulated_source_hit,
        "simulated_keyword_hit": simulated_keyword_hit,
        "expected_improvement_reason": expected_improvement_reason,
        "requires_production_change": policy.requires_production_change,
        "policy_case_derivation": row.get("policy_case_derivation"),
        "notes": "; ".join(notes),
    }


def build_summary(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    calibrated_taxonomy_rows: list[dict[str, Any]],
    calibrated_summary: dict[str, Any],
    discovered_inputs: dict[str, Path],
) -> dict[str, Any]:
    status_counts = Counter(row["simulation_status"] for row in results)
    derivation_counts = Counter(row["policy_case_derivation"] for row in cases)
    return {
        "phase": "6E-0_to_6E-3",
        "total_remaining_bad_cases": len(cases),
        "source_artifact_calibrated_bad_count": calibrated_summary.get("calibrated_bad_count"),
        "source_artifact_calibrated_taxonomy_rows": len(calibrated_taxonomy_rows),
        "final_closure_target_distribution": FINAL_POLICY_DISTRIBUTION,
        "by_query_type": dict(Counter(row["query_type"] for row in cases)),
        "by_original_query_type": dict(Counter(row.get("original_query_type") for row in cases)),
        "by_recommended_policy": dict(Counter(row["recommended_policy"] for row in results)),
        "by_simulation_status": dict(status_counts),
        "by_policy_case_derivation": dict(derivation_counts),
        "simulated_improvable_count": status_counts.get("offline_rule_estimate", 0),
        "design_only_count": status_counts.get("design_only", 0),
        "requires_production_change_count": sum(
            1 for row in results if row.get("requires_production_change")
        ),
        "recommended_phase6e4_eval": True,
        "writes_chroma": False,
        "calls_llm": False,
        "modifies_agent_api": False,
        "artifact_consistency_note": (
            "Phase 6D Final Closure records 59 remaining policy cases. "
            "Current committed Phase 6D-9 calibrated taxonomy has a different row count, "
            "so this simulator records original_query_type and policy_query_type separately."
        ),
        "input_files": {key: path.name for key, path in discovered_inputs.items()},
    }


def build_phase6e5_probe(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    probe_rows: list[dict[str, Any]] = []
    for case, result in zip(cases, results):
        selected_policy = result["recommended_policy"]
        probe_rows.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "query_type": case["query_type"],
                "original_query_type": case.get("original_query_type"),
                "policy_mode": "query_type_aware",
                "selected_policy": selected_policy,
                "metadata_first_applied": selected_policy == "metadata_first",
                "sparse_first_applied": selected_policy == "sparse_first_bm25",
                "dense_sparse_fusion_applied": selected_policy == "dense_sparse_fusion",
                "clarification_first_applied": selected_policy == "clarification_first",
                "citation_evidence_checked": selected_policy == "citation_aware_evidence",
                "requires_clarification": selected_policy == "clarification_first",
                "simulation_status": result["simulation_status"],
                "requires_production_change": result["requires_production_change"],
                "notes": result["notes"],
            }
        )

    policy_counts = Counter(row["selected_policy"] for row in probe_rows)
    summary = {
        "phase": "6E-5_local_policy_probe",
        "policy_mode": "query_type_aware",
        "total_cases": len(probe_rows),
        "by_query_type": dict(Counter(row["query_type"] for row in probe_rows)),
        "by_selected_policy": dict(policy_counts),
        "metadata_first_count": policy_counts.get("metadata_first", 0),
        "sparse_first_count": policy_counts.get("sparse_first_bm25", 0),
        "dense_sparse_fusion_count": policy_counts.get("dense_sparse_fusion", 0),
        "clarification_first_count": policy_counts.get("clarification_first", 0),
        "citation_aware_count": policy_counts.get("citation_aware_evidence", 0),
        "baseline_default_unchanged": True,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
        "recommended_hpc_full_eval": True,
    }
    return probe_rows, summary


def build_phase6e7_gated_probe(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    probe_rows: list[dict[str, Any]] = []
    for case in cases:
        decision = decide_gated_retrieval_policy(
            case["query"],
            {"query_type": case["query_type"]},
        )
        selected_policy = decision.policy.name.value
        probe_rows.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "query_type": case["query_type"],
                "original_query_type": case.get("original_query_type"),
                "policy_mode": "query_type_aware",
                "selected_policy": selected_policy,
                "gated_policy_enabled": decision.gated_policy_enabled,
                "fallback_to_baseline": decision.fallback_to_baseline,
                "gated_reason": decision.gated_reason,
                "metadata_first_applied": (
                    decision.gated_policy_enabled and selected_policy == "metadata_first"
                ),
                "sparse_first_applied": (
                    decision.gated_policy_enabled and selected_policy == "sparse_first_bm25"
                ),
                "citation_evidence_checked": (
                    decision.gated_policy_enabled and selected_policy == "citation_aware_evidence"
                ),
                "clarification_debug_only": (
                    not decision.gated_policy_enabled and selected_policy == "clarification_first"
                ),
                "calls_llm": False,
                "writes_chroma": False,
            }
        )

    selected_policy_counts = Counter(row["selected_policy"] for row in probe_rows)
    summary = {
        "phase": "6E-7_gated_policy_probe",
        "policy_mode": "query_type_aware",
        "total_cases": len(probe_rows),
        "by_query_type": dict(Counter(row["query_type"] for row in probe_rows)),
        "by_selected_policy": dict(selected_policy_counts),
        "gated_enabled_count": sum(1 for row in probe_rows if row["gated_policy_enabled"]),
        "fallback_to_baseline_count": sum(1 for row in probe_rows if row["fallback_to_baseline"]),
        "metadata_first_count": sum(1 for row in probe_rows if row["metadata_first_applied"]),
        "sparse_first_count": sum(1 for row in probe_rows if row["sparse_first_applied"]),
        "citation_aware_count": sum(1 for row in probe_rows if row["citation_evidence_checked"]),
        "clarification_debug_only_count": sum(
            1 for row in probe_rows if row["clarification_debug_only"]
        ),
        "baseline_default_unchanged": True,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
        "recommended_hpc_full_eval": True,
    }
    return probe_rows, summary


def build_phase6e9_conservative_probe(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    probe_rows: list[dict[str, Any]] = []
    for case in cases:
        decision = decide_gated_retrieval_policy(
            case["query"],
            {"query_type": case["query_type"]},
        )
        selected_policy = decision.policy.name.value
        probe_rows.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "query_type": case["query_type"],
                "original_query_type": case.get("original_query_type"),
                "policy_mode": "query_type_aware",
                "selected_policy": selected_policy,
                "conservative_gate_enabled": decision.gated_policy_enabled,
                "fallback_to_baseline": decision.fallback_to_baseline,
                "gated_reason": decision.gated_reason,
                "metadata_first_applied": (
                    decision.gated_policy_enabled and selected_policy == "metadata_first"
                ),
                "sparse_first_applied": (
                    decision.gated_policy_enabled and selected_policy == "sparse_first_bm25"
                ),
                "citation_evidence_checked": (
                    decision.gated_policy_enabled and selected_policy == "citation_aware_evidence"
                ),
                "clarification_debug_only": (
                    not decision.gated_policy_enabled and selected_policy == "clarification_first"
                ),
                "strong_signal_required": True,
                "calls_llm": False,
                "writes_chroma": False,
            }
        )

    fastapi_probe_decision = decide_gated_retrieval_policy("FastAPI 里 Request Body 如何定义？")
    selected_policy_counts = Counter(row["selected_policy"] for row in probe_rows)
    summary = {
        "phase": "6E-9_conservative_gate_probe",
        "policy_mode": "query_type_aware",
        "total_cases": len(probe_rows),
        "by_query_type": dict(Counter(row["query_type"] for row in probe_rows)),
        "by_selected_policy": dict(selected_policy_counts),
        "conservative_gate_enabled_count": sum(
            1 for row in probe_rows if row["conservative_gate_enabled"]
        ),
        "fallback_to_baseline_count": sum(1 for row in probe_rows if row["fallback_to_baseline"]),
        "metadata_first_count": sum(1 for row in probe_rows if row["metadata_first_applied"]),
        "sparse_first_count": sum(1 for row in probe_rows if row["sparse_first_applied"]),
        "citation_aware_count": sum(1 for row in probe_rows if row["citation_evidence_checked"]),
        "clarification_debug_only_count": sum(
            1 for row in probe_rows if row["clarification_debug_only"]
        ),
        "strong_signal_required": True,
        "baseline_default_unchanged": True,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
        "recommended_hpc_full_eval": True,
        "fastapi_request_body_probe": {
            "query": "FastAPI 里 Request Body 如何定义？",
            "inferred_query_type": fastapi_probe_decision.query_type.value,
            "selected_policy": fastapi_probe_decision.policy.name.value,
            "conservative_gate_enabled": fastapi_probe_decision.gated_policy_enabled,
            "fallback_to_baseline": fastapi_probe_decision.fallback_to_baseline,
            "gated_reason": fastapi_probe_decision.gated_reason,
        },
    }
    return probe_rows, summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    discovered = discover_inputs(EVALUATION_DIR)
    taxonomy_path = discovered.get("calibrated_taxonomy")
    if taxonomy_path is None:
        raise FileNotFoundError("No Phase 6D-9 calibrated taxonomy JSONL file was found.")

    taxonomy_rows = read_jsonl(taxonomy_path)
    result_rows = read_jsonl(discovered.get("agent_results", Path()))
    expanded_rows = read_jsonl(discovered.get("expanded_cases", Path()))
    calibrated_summary = read_json(discovered.get("calibrated_summary", Path()))
    candidates = merge_case_rows(taxonomy_rows, result_rows, expanded_rows)
    cases = build_remaining_bad_cases(candidates)
    results = [simulate_case(row) for row in cases]
    summary = build_summary(cases, results, taxonomy_rows, calibrated_summary, discovered)

    write_jsonl(args.cases_output, cases)
    write_jsonl(args.results_output, results)
    write_json(args.summary_output, summary)
    probe_rows, probe_summary = build_phase6e5_probe(cases, results)
    write_jsonl(args.phase6e5_probe_results_output, probe_rows)
    write_json(args.phase6e5_probe_summary_output, probe_summary)
    if args.write_phase6e7_probe:
        gated_probe_rows, gated_probe_summary = build_phase6e7_gated_probe(cases)
        write_jsonl(args.phase6e7_probe_results_output, gated_probe_rows)
        write_json(args.phase6e7_probe_summary_output, gated_probe_summary)
    conservative_rows, conservative_summary = build_phase6e9_conservative_probe(cases)
    write_jsonl(args.phase6e9_probe_results_output, conservative_rows)
    write_json(args.phase6e9_probe_summary_output, conservative_summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6E offline retrieval policy simulator.")
    parser.add_argument("--cases-output", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--results-output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument(
        "--phase6e5-probe-results-output",
        type=Path,
        default=DEFAULT_PHASE6E5_PROBE_RESULTS_PATH,
    )
    parser.add_argument(
        "--phase6e5-probe-summary-output",
        type=Path,
        default=DEFAULT_PHASE6E5_PROBE_SUMMARY_PATH,
    )
    parser.add_argument(
        "--phase6e7-probe-results-output",
        type=Path,
        default=DEFAULT_PHASE6E7_PROBE_RESULTS_PATH,
    )
    parser.add_argument(
        "--phase6e7-probe-summary-output",
        type=Path,
        default=DEFAULT_PHASE6E7_PROBE_SUMMARY_PATH,
    )
    parser.add_argument(
        "--write-phase6e7-probe",
        action="store_true",
        help="Rewrite Phase 6E-7 probe outputs. Disabled by default to preserve historical output.",
    )
    parser.add_argument(
        "--phase6e9-probe-results-output",
        type=Path,
        default=DEFAULT_PHASE6E9_PROBE_RESULTS_PATH,
    )
    parser.add_argument(
        "--phase6e9-probe-summary-output",
        type=Path,
        default=DEFAULT_PHASE6E9_PROBE_SUMMARY_PATH,
    )
    return parser.parse_args()


def main() -> None:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
