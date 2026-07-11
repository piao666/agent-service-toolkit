"""Aggregate reproducible backend closure evidence without running embeddings or HPC jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "enterprise_kb_v1"
MANIFEST = REPORTS / "phase10_backend_closure_manifest.json"
SUMMARY = REPORTS / "phase10_backend_closure_report.md"
HPC_HANDOFF = REPORTS / "phase10_hpc_evaluation_handoff.md"

LOCAL_REPORTS = (
    ("backend_security", "phase10_backend_security_smoke.json", "passed"),
    ("custom_graph", "phase5_custom_graph_smoke.json", "overall_pass"),
    ("graph_api", "phase5b_graph_api_smoke.json", "overall_pass"),
    ("citation_guard", "phase5_citation_guard_smoke.json", "all_pass"),
    ("session_memory", "phase7_memory_smoke.json", "overall_pass"),
    ("session_memory_api", "phase7_memory_graph_api_smoke.json", "overall_pass"),
    ("long_term_memory", "phase8_long_term_memory_smoke.json", "overall_pass"),
    ("long_term_memory_api", "phase8_memory_api_smoke.json", "overall_pass"),
    ("grounding_memory", "phase10_p1_grounding_memory_smoke.json", "passed"),
)
HPC_REPORT = REPORTS / "phase6f_multichannel_retrieval_eval_results.json"


def _read_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def build_manifest() -> dict[str, Any]:
    local_results: list[dict[str, Any]] = []
    for name, filename, pass_field in LOCAL_REPORTS:
        path = REPORTS / filename
        data = _read_json(path)
        local_results.append(
            {
                "name": name,
                "passed": data.get(pass_field) is True,
                "pass_field": pass_field,
                "timestamp": data.get("timestamp", ""),
                "artifact": _artifact(path),
            }
        )

    hpc = _read_json(HPC_REPORT)
    hpc_snapshot = {
        "evidence_status": "historical_not_rerun_in_this_closure",
        "artifact": _artifact(HPC_REPORT),
        "environment": hpc.get("environment"),
        "timestamp": hpc.get("timestamp"),
        "total_cases": hpc.get("total_cases"),
        "cases_with_expected_source_ids": hpc.get("cases_with_expected_sids"),
        "index_status": hpc.get("index_status", {}),
        "baseline": hpc.get("baseline", {}),
        "multichannel": hpc.get("multichannel", {}),
        "delta": hpc.get("delta", {}),
        "failed_case_count": hpc.get("failed_case_count"),
        "overall_pass": hpc.get("overall_pass"),
        "route_metric_note": hpc.get("route_metric_note", ""),
    }
    local_overall_pass = all(item["passed"] for item in local_results)
    return {
        "phase": "phase10_backend_closure",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "local_lightweight_backend_validation_no_embeddings_no_index_rebuild",
        "local_overall_pass": local_overall_pass,
        "local_results": local_results,
        "historical_hpc_evidence": hpc_snapshot,
        "known_blockers": [
            {
                "name": "real_qwen_max_flow",
                "status": "blocked",
                "observed_error": "provider_http_error:403",
                "meaning": "Fail-closed behavior is correct; credentials, account access, or quota must be repaired before rerun.",
            }
        ],
        "claim_boundaries": [
            "The local closure uses explicit mock mode and does not measure real LLM answer quality.",
            "The Phase 6F snapshot is historical HPC evidence and was not rerun by this collector.",
            "Historical Phase 6F citation_validity does not prove semantic support; P1 checks semantic support only on controlled fixtures.",
            "Registry source counts must be deduplicated by source identity and must not be added across overlapping registries.",
            "No production user count, traffic, hallucination rate, revenue, or business savings claim is supported.",
        ],
    }


def write_summary(manifest: dict[str, Any]) -> None:
    rows = [
        f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | "
        f"{item['artifact']['path']} | {item['artifact']['sha256'][:12]} |"
        for item in manifest["local_results"]
    ]
    hpc = manifest["historical_hpc_evidence"]
    multi = hpc["multichannel"]
    delta = hpc["delta"]
    index = hpc["index_status"]
    text = f"""# Phase 10 Backend Closure

Generated: {manifest["generated_at"]}

## Local lightweight validation

Overall: **{"PASS" if manifest["local_overall_pass"] else "FAIL"}**

| Check | Result | Evidence | SHA-256 prefix |
|---|---:|---|---|
{chr(10).join(rows)}

These checks used explicit mock mode. They validate orchestration, API contracts,
citation guards, project-scoped session memory, governed long-term-memory
lifecycle, and controlled grounding fixtures. They do not validate real Qwen
answer quality or rerun embeddings.

## Historical HPC evidence

Evidence status: **{hpc["evidence_status"]}**

- Environment: {hpc["environment"]}
- Cases: {hpc["total_cases"]} total; {hpc["cases_with_expected_source_ids"]} with expected source IDs
- Index snapshot: {index.get("official_chunk_count")} official chunks; {index.get("internal_chunk_count")} internal chunks
- Multichannel hit@3: {multi.get("hit_at_3")}
- Multichannel hit@10: {multi.get("hit_at_10")}
- Multichannel MRR: {multi.get("mrr")}
- Dual accuracy: {multi.get("dual_accuracy")}
- Citation validity: {multi.get("citation_validity")}
- Failed cases: {hpc["failed_case_count"]}
- Delta vs baseline: hit@3 {delta.get("hit_at_3_delta")}, hit@10 {delta.get("hit_at_10_delta")}, MRR {delta.get("mrr_delta")}

The route metric remains governed by the note in the source JSON; this report
does not reinterpret the denominator.

## Open blocker

The real qwen-max flow returned HTTP 403 and correctly failed closed. Repair the
provider credential/account/quota state, then rerun the real-provider API flow.
Do not convert this failure into a mock success.

## Claim boundaries

{chr(10).join(f"- {item}" for item in manifest["claim_boundaries"])}
"""
    SUMMARY.write_text(text, encoding="utf-8")


def write_hpc_handoff() -> None:
    text = """# Phase 10 HPC Evaluation Handoff

This handoff does not execute an HPC job. It identifies the existing entrypoints
and the evidence that must return before a new success claim is made.

## Existing inputs

- Evaluation script: scripts/enterprise_kb_v1/run_phase6f_multichannel_retrieval_eval.py
- Config smoke: scripts/enterprise_kb_v1/smoke_phase6f_eval_config.py
- Command reference: reports/enterprise_kb_v1/phase6f_hpc_run_commands.md
- Gold corrections: reports/enterprise_kb_v1/phase6f_gold_correction_notes.md
- Historical result: reports/enterprise_kb_v1/phase6f_multichannel_retrieval_eval_results.json
- Historical per-case evidence: reports/enterprise_kb_v1/phase6f_per_case_results.jsonl

## Required rerun order

1. Sync the committed backend code to the existing HPC checkout.
2. Verify both existing Chroma indexes and configured bge-m3 model paths.
3. Run the Phase 6F config smoke before the evaluation.
4. Use the exact command and environment documented in phase6f_hpc_run_commands.md.
5. Return both the aggregate JSON and per-case JSONL; an aggregate report alone is insufficient.
6. Compare case count, expected-source coverage, index counts, warnings, failed cases, and route metric note.
7. Treat any missing index, missing per-case evidence, or changed denominator as a failed or insufficient-evidence run.

## Acceptance fields

- environment must identify HPC
- indices_ready must be true
- total_cases and cases_with_expected_sids must be present
- official and internal chunk counts must be present
- baseline, multichannel, and delta metrics must be present
- dual_accuracy and citation_validity must be present
- failed_case_count and warnings must be present
- overall_pass must be recomputed by the script
- per-case output must cover every declared case

## Separate real-provider rerun

After repairing the qwen-max HTTP 403, run the Graph API with
ALLOW_LLM_FALLBACK=false and record requested provider/model, actual
provider/model, fallback_used, HTTP status, citations, citation semantic
support, and memory traces. Never include API keys or AUTH_SECRET in logs.
"""
    HPC_HANDOFF.write_text(text, encoding="utf-8")


def main() -> int:
    manifest = build_manifest()
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_summary(manifest)
    write_hpc_handoff()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["local_overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
