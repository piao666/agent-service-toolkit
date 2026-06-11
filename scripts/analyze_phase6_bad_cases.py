from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
DOCS_DIR = ROOT_DIR / "docs" / "enterprise_rag_backend"
RETRIEVAL_RESULTS_PATH = EVAL_DIR / "phase6_retrieval_eval_results.jsonl"
API_RESULTS_PATH = EVAL_DIR / "phase6_api_eval_results.jsonl"
RETRIEVAL_SUMMARY_PATH = EVAL_DIR / "phase6_retrieval_eval_summary.json"
API_SUMMARY_PATH = EVAL_DIR / "phase6_api_eval_summary.json"
BAD_CASES_PATH = EVAL_DIR / "phase6_bad_cases.jsonl"
QA_DOC_PATH = DOCS_DIR / "PHASE6_QA_EVALUATION.md"
BAD_CASE_DOC_PATH = DOCS_DIR / "PHASE6_BAD_CASE_ANALYSIS.md"
SYSTEM_GAP_DOC_PATH = DOCS_DIR / "PHASE6_SYSTEM_GAP_ANALYSIS.md"
LOW_RELEVANCE_THRESHOLD = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Phase 6C retrieval and API bad cases.")
    parser.add_argument("--retrieval-results", type=Path, default=RETRIEVAL_RESULTS_PATH)
    parser.add_argument("--api-results", type=Path, default=API_RESULTS_PATH)
    parser.add_argument("--retrieval-summary", type=Path, default=RETRIEVAL_SUMMARY_PATH)
    parser.add_argument("--api-summary", type=Path, default=API_SUMMARY_PATH)
    parser.add_argument("--bad-cases", type=Path, default=BAD_CASES_PATH)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _bad_case(
    row: dict[str, Any],
    eval_mode: str,
    bad_case_type: str,
    diagnosis: str,
    suggested_fix: str,
) -> dict[str, Any]:
    return {
        "case_id": row.get("case_id"),
        "query": row.get("query"),
        "eval_mode": eval_mode,
        "bad_case_type": bad_case_type,
        "expected_source_ids": row.get("expected_source_ids", []),
        "actual_source_ids": row.get("returned_source_ids", []),
        "diagnosis": diagnosis,
        "suggested_fix": suggested_fix,
    }


def _retrieval_bad_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bad_cases: list[dict[str, Any]] = []
    for row in rows:
        if row.get("empty_result"):
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "empty_retrieval",
                    "The vector search returned no reviewed chunks for this query.",
                    "Check query wording, chunk coverage, and whether the source is reviewed.",
                )
            )
        if int(row.get("banned_source_result_count") or 0) > 0:
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "banned_source_returned",
                    "A result from a source excluded by ingestion policy was returned.",
                    "Recheck the ingestion candidate filter and collection contents.",
                )
            )
        if int(row.get("invalid_result_count") or 0) > 0:
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "invalid_result",
                    "At least one result was not marked as an approved ingestion candidate.",
                    "Inspect Chroma metadata and ingestion manifest consistency.",
                )
            )
        if not row.get("negative") and not row.get("source_hit_at_k"):
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "source_miss",
                    "The expected source id was not present in top-k retrieval results.",
                    "Review chunk coverage, query wording, and embedding similarity behavior.",
                )
            )
        if not row.get("negative") and not row.get("doc_type_hit_at_k"):
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "doc_type_miss",
                    "The expected document type was not present in top-k retrieval results.",
                    "Check whether the relevant format has enough reviewed chunks.",
                )
            )
        if not row.get("negative") and not row.get("keyword_hit_at_k"):
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "keyword_miss",
                    "Expected keywords were not found in retrieved chunk text.",
                    "Improve case wording or add more representative reviewed source chunks.",
                )
            )
        relevance = row.get("best_relevance_score")
        if relevance is not None and float(relevance) < LOW_RELEVANCE_THRESHOLD:
            bad_cases.append(
                _bad_case(
                    row,
                    "retrieval",
                    "low_relevance_score",
                    "The top retrieval score was below the review threshold.",
                    "Inspect the top chunk and consider query rewriting or chunk boundary changes.",
                )
            )
    return bad_cases


def _api_bad_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bad_cases: list[dict[str, Any]] = []
    for row in rows:
        if row.get("api_eval_status") in {"error", "skipped"}:
            bad_cases.append(
                _bad_case(
                    row,
                    "api",
                    "api_error",
                    str(row.get("error_summary") or "Endpoint evaluation did not complete."),
                    "Start the local service with a configured provider before rerunning endpoint evaluation.",
                )
            )
            continue
        if row.get("fallback_triggered"):
            bad_cases.append(
                _bad_case(
                    row,
                    "api",
                    "api_fallback",
                    "The endpoint returned a fallback response.",
                    "Inspect retrieval debug and model provider configuration for this case.",
                )
            )
        if not row.get("whether_expected_source_hit"):
            bad_cases.append(
                _bad_case(
                    row,
                    "api",
                    "answer_source_miss",
                    "The endpoint response sources did not include the expected source id.",
                    "Compare endpoint retrieval settings with the reviewed collection.",
                )
            )
        if not row.get("whether_expected_keywords_in_answer"):
            bad_cases.append(
                _bad_case(
                    row,
                    "api",
                    "answer_missing_expected_keyword",
                    "The answer preview did not include expected keywords.",
                    "Review answer synthesis prompt behavior and returned context.",
                )
            )
    return bad_cases


def _table_line(mapping: dict[str, Any], keys: list[str]) -> str:
    return "| " + " | ".join(str(mapping.get(key, "")) for key in keys) + " |"


def _write_qa_doc(retrieval_summary: dict[str, Any], api_summary: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    content = f"""# Phase 6C QA Evaluation

## Corrected Conclusion

Retrieval-only evaluation completed on reviewed Chroma sample.
API/Agent endpoint evaluation was skipped because local service was unavailable.
No end-to-end Agent QA success is claimed.

This document must not be read as proof that end-to-end Agent/API evaluation passed, that the complete QA evaluation loop is finished, or that the RAG system is production ready.

## Goal And Boundary

Phase 6C currently provides a retrieval-only evaluation baseline for the reviewed Phase 6 corpus. API/Agent endpoint evaluation is represented in the output schema, but the local endpoint run was skipped and should be rerun after the local service and provider configuration are available.

## Evaluation Scope

The evaluation reads the reviewed Chroma collection `enterprise_ai_learning_kb_reviewed` from `chroma_enterprise_phase6`. It does not create a new collection, expand the ingestion scope, or modify production endpoint behavior.

## Local Knowledge Base Layout

```text
data/knowledge_base/
  raw/                 # ignored raw downloaded/local source cache
  normalized/          # ignored normalized text cache
  chunks/              # ignored chunk text cache
  manifests/           # committed metadata/report manifests
  evaluation/          # committed evaluation cases/results/summaries

chroma_enterprise_phase6/
  # ignored local Chroma vector store

collection_name:
  enterprise_ai_learning_kb_reviewed
```

## QA Case Design

The case file is `data/knowledge_base/evaluation/phase6_qa_cases.jsonl`. It contains positive cases for deep learning, NLP, AI Agent concepts, FastAPI documentation, and repository metadata, plus negative cases that verify banned sources are not returned.

## Retrieval Metrics

| metric | value |
| --- | --- |
| case_count | {retrieval_summary.get("case_count", 0)} |
| positive_case_count | {retrieval_summary.get("positive_case_count", 0)} |
| negative_case_count | {retrieval_summary.get("negative_case_count", 0)} |
| source_hit_at_k | {retrieval_summary.get("source_hit_at_k", 0)} |
| doc_type_hit_at_k | {retrieval_summary.get("doc_type_hit_at_k", 0)} |
| keyword_hit_at_k | {retrieval_summary.get("keyword_hit_at_k", 0)} |
| top1_source_hit | {retrieval_summary.get("top1_source_hit", 0)} |
| mrr_source | {retrieval_summary.get("mrr_source", 0)} |
| empty_result_count | {retrieval_summary.get("empty_result_count", 0)} |
| banned_source_result_count | {retrieval_summary.get("banned_source_result_count", 0)} |
| invalid_result_count | {retrieval_summary.get("invalid_result_count", 0)} |

Retrieval evaluation calls the local embedding model to encode queries, reads Chroma, and stores only metadata plus short previews.

## API Metrics

| metric | value |
| --- | --- |
| api_eval_status | {api_summary.get("api_eval_status", "not_run")} |
| case_count_selected | {api_summary.get("case_count_selected", 0)} |
| case_count_run | {api_summary.get("case_count_run", 0)} |
| expected_source_hit_rate | {api_summary.get("expected_source_hit_rate", 0)} |
| expected_keyword_hit_rate | {api_summary.get("expected_keyword_hit_rate", 0)} |
| fallback_count | {api_summary.get("fallback_count", 0)} |
| error_count | {api_summary.get("error_count", 0)} |
| avg_latency_ms | {api_summary.get("avg_latency_ms", "")} |
| calls_llm | {api_summary.get("calls_llm", False)} |
| end_to_end_agent_eval_passed | {api_summary.get("end_to_end_agent_eval_passed", False)} |

Endpoint evaluation was skipped and should be rerun after the local service and provider configuration are available.

## Embedding Limitations

The current embedding route uses a local small Chinese embedding model. It is suitable for a Chinese semantic retrieval smoke test, but it is limited for mixed Chinese/English documents, English API documentation, code snippets, function names, class names, configuration fields, exact identifiers, order numbers, paths, and cross-language query-document matching.

Follow-up options include evaluating multilingual embeddings, evaluating code-aware embeddings, using hybrid retrieval, separately evaluating English technical documentation, and creating a dedicated mixed-language QA set. The current embedding model should not be described as the production-best solution.

## Chunking Strategy Gaps

Phase 6B chunking is an engineering validation baseline, not a final chunking strategy. Different source formats need different strategies:

- DOCX: title hierarchy plus paragraph aggregation.
- PDF: page number plus heading/paragraph recovery, with header and footer cleanup when needed.
- HTML: main/article extraction plus heading splitting, with navigation, sidebar, and footer filtering.
- Markdown: heading splitting with code block protection.
- JSON/YAML: key path or object-structure splitting.
- CSV/Table: header, row group, and field-semantics-aware splitting.
- Code/API documentation: preserve function signatures, parameter descriptions, and example code instead of hard cuts.

The current phase has not completed semantic chunking, chunk size and overlap tuning, chunk-level ablation, reranker before/after chunk quality comparison, or formal validation for PDF tables, scanned files, and two-column papers.

## Intent Recognition Gaps

The current evaluation does not systematically validate user intent recognition, including knowledge lookup, business action calls, chit-chat, summarization or rewriting, exact lookup for identifiers and fields, multi-turn follow-up, or questions that do not need retrieval.

A later router evaluation should use intent labels such as:

```text
intent = knowledge_lookup / business_action / chit_chat / exact_lookup / unsupported / clarification_needed
```

Current results should not be used to claim stable query routing.

## Retrieval Strategy Gaps

The current retrieval evaluation is primarily dense vector retrieval over a small reviewed sample. Production-grade retrieval still needs BM25 or keyword retrieval, dense plus sparse hybrid retrieval, exact matching, metadata filters, reranking, top-k policy, score thresholding, query rewriting, multi-query retrieval, source diversity control, and negative query handling.

Pure vector retrieval is weak for exact identifiers, order numbers, API names, file paths, config keys, and short keyword queries.

A possible future scoring direction is:

```text
hybrid_score = alpha * dense_score + beta * sparse_score + gamma * metadata_match_score
```

This is a future plan only and is not implemented in Phase 6C.

## Current Limitations

The reviewed collection is intentionally small and metadata controlled. Phase 6C reports retrieval evidence for this reviewed sample only and does not claim production accuracy. Some misses may be caused by limited source coverage, chunk boundaries, mixed Chinese and English terminology, and the current dense-only retrieval strategy.

## Next Improvements

Recommended follow-up work is to inspect bad cases, design intent routing evaluation, prototype hybrid retrieval, evaluate reranking, run chunking ablation, and rerun endpoint evaluation after the local service is available.
"""
    QA_DOC_PATH.write_text(content, encoding="utf-8", newline="\n")


def _write_bad_case_doc(
    bad_cases: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
    api_summary: dict[str, Any],
) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    counts = Counter(str(case.get("bad_case_type")) for case in bad_cases)
    type_rows = [
        {"type": bad_type, "count": count}
        for bad_type, count in sorted(counts.items(), key=lambda item: item[0])
    ]
    lines = [
        "# Phase 6C Bad Case Analysis",
        "",
        "## Scope",
        "",
        "This report analyzes Phase 6C retrieval-only results and the skipped endpoint evaluation record. It does not modify retrieval logic, endpoint behavior, or Chroma contents.",
        "",
        "## Corrected Conclusion",
        "",
        "Retrieval-only evaluation completed on reviewed Chroma sample. API/Agent endpoint evaluation was skipped because local service was unavailable. No end-to-end Agent QA success is claimed.",
        "",
        "## Summary",
        "",
        f"- bad_case_count: {len(bad_cases)}",
        f"- retrieval_case_count: {retrieval_summary.get('case_count', 0)}",
        f"- api_eval_status: {api_summary.get('api_eval_status', 'not_run')}",
        f"- api_case_count_run: {api_summary.get('case_count_run', 0)}",
        "",
        "## Bad Case Types",
        "",
        "| bad_case_type | count |",
        "| --- | --- |",
    ]
    lines.extend(_table_line(row, ["type", "count"]) for row in type_rows)
    lines.extend(
        [
            "",
            "## Diagnosis Categories",
            "",
            "- `source_miss`: expected source was absent from top-k retrieval.",
            "- `doc_type_miss`: expected document type was absent from top-k retrieval.",
            "- `keyword_miss`: expected keywords were absent from retrieved chunk text.",
            "- `banned_source_returned`: a policy-excluded source was returned.",
            "- `api_error`: endpoint evaluation was skipped or failed.",
            "- `api_fallback`: endpoint returned a fallback response.",
            "- `answer_missing_expected_keyword`: endpoint answer did not include expected keywords.",
            "- `answer_source_miss`: endpoint sources did not include the expected source.",
            "",
            "## Current Constraints",
            "",
        "The current reviewed collection has limited sample coverage. Retrieval failures should be treated as corpus and pipeline feedback, not as production accuracy numbers.",
        "",
        "## Embedding Limitations",
        "",
        "The current local small Chinese embedding model is useful for a Chinese retrieval smoke test, but it is limited for mixed Chinese/English documents, English API documentation, code snippets, function names, class names, configuration fields, exact identifiers, order numbers, paths, and cross-language matching.",
        "",
        "Future work should evaluate multilingual embeddings, code-aware embeddings, hybrid retrieval, English technical-document cases, and mixed-language QA cases. The current model should not be presented as a production-best embedding choice.",
        "",
        "## Suggested Fixes",
            "",
            "Prioritize inspecting high-frequency bad case types, then adjust source coverage, chunk boundaries, or query wording. Endpoint-specific issues should be rerun only after the local service and configured provider are confirmed available.",
        ]
    )
    BAD_CASE_DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_system_gap_doc(retrieval_summary: dict[str, Any], api_summary: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    content = f"""# Phase 6C System Gap Analysis

## Current Validated Scope

- Retrieval-only evaluation completed on reviewed Chroma sample.
- The evaluated collection is `enterprise_ai_learning_kb_reviewed`.
- The evaluated vector store directory is `chroma_enterprise_phase6`, which is ignored local state.
- Retrieval output validation confirmed `banned_source_result_count={retrieval_summary.get("banned_source_result_count", 0)}` and `invalid_result_count={retrieval_summary.get("invalid_result_count", 0)}`.

## Not Yet Validated Scope

- End-to-end Agent/API QA success is not validated.
- Production retrieval quality is not validated.
- Query routing stability is not validated.
- Intent recognition is not validated.
- Hybrid retrieval, reranking, and chunking ablation are not validated.
- Large-scale corpus ingestion is not validated.

## Local Knowledge Base Location

```text
data/knowledge_base/
  raw/                 # ignored raw downloaded/local source cache
  normalized/          # ignored normalized text cache
  chunks/              # ignored chunk text cache
  manifests/           # committed metadata/report manifests
  evaluation/          # committed evaluation cases/results/summaries

chroma_enterprise_phase6/
  # ignored local Chroma vector store

collection_name:
  enterprise_ai_learning_kb_reviewed
```

## Embedding Limitations

The current embedding route uses a local small Chinese embedding model. It is appropriate for a Chinese semantic retrieval smoke test, but it has limitations for:

- Mixed Chinese/English documents.
- English API documentation.
- Code snippets.
- Function names, class names, and configuration fields.
- Exact identifiers, order numbers, and paths.
- Cross-language query-document matching.

Future work should evaluate multilingual embeddings, code-aware embeddings, hybrid retrieval, English technical-document test cases, and mixed-language QA cases.

## Chunking Strategy Gaps

Current chunking is a Phase 6B engineering baseline. Format-specific gaps remain:

- DOCX needs title hierarchy plus paragraph aggregation.
- PDF needs page number plus heading/paragraph recovery, and header/footer cleanup when needed.
- HTML needs main/article extraction, heading splitting, and navigation/sidebar/footer filtering.
- Markdown needs heading splitting with code block protection.
- JSON/YAML needs key path or object-structure splitting.
- CSV/Table needs header, row group, and field-semantics-aware splitting.
- Code/API documentation needs function signatures, parameter descriptions, and examples preserved.

Not yet completed: semantic chunking, chunk size and overlap tuning, chunk-level ablation, reranker before/after comparison, and formal validation for PDF tables, scanned files, and two-column papers.

## Intent Recognition Gaps

The project has not systematically evaluated whether a user request is:

- `knowledge_lookup`
- `business_action`
- `chit_chat`
- `exact_lookup`
- `unsupported`
- `clarification_needed`

Intent test cases should cover knowledge-base questions, business-system calls, chit-chat, summarization and rewriting, exact lookup for identifiers or fields, multi-turn follow-up, and questions that do not need retrieval.

Current results cannot be used to claim stable query routing.

## Retrieval Strategy Gaps

The current strategy is primarily dense vector retrieval. Production-grade retrieval still needs:

- BM25 or keyword retrieval.
- Dense plus sparse hybrid retrieval.
- Exact matching.
- Metadata filters.
- Reranking.
- Top-k policy.
- Score thresholding.
- Query rewriting.
- Multi-query retrieval.
- Source diversity control.
- Negative query handling.

Pure vector retrieval is weak for exact identifiers, order numbers, API names, file paths, config keys, and short keyword queries.

Future hybrid scoring can be evaluated with:

```text
hybrid_score = alpha * dense_score + beta * sparse_score + gamma * metadata_match_score
```

This is only a proposed direction and is not implemented in Phase 6C.

## API/Agent Eval Skipped Status

Endpoint evaluation was skipped and should be rerun after the local service and provider configuration are available.

```json
{{
  "api_eval_status": "{api_summary.get("api_eval_status", "skipped")}",
  "skip_reason": "{api_summary.get("skip_reason", "local_service_unavailable")}",
  "case_count_run": {api_summary.get("case_count_run", 0)},
  "calls_llm": {str(api_summary.get("calls_llm", False)).lower()},
  "end_to_end_agent_eval_passed": {str(api_summary.get("end_to_end_agent_eval_passed", False)).lower()}
}}
```

## Required Work Before Claiming Production Readiness

- Run endpoint evaluation with the local service and configured provider available.
- Add intent routing tests and confusion analysis.
- Compare dense-only retrieval with hybrid retrieval.
- Evaluate reranking on the reviewed corpus.
- Run chunking ablation by format and topic.
- Expand reviewed source coverage through controlled ingestion.
- Add negative and exact-lookup cases for identifiers, field names, and short keyword queries.

## Proposed Phase 6D Plan

- Phase 6D-1: Intent routing evaluation.
- Phase 6D-2: Hybrid retrieval prototype.
- Phase 6D-3: Reranker evaluation.
- Phase 6D-4: Chunking ablation.
- Phase 6D-5: End-to-end Agent/API evaluation after service is available.

This plan is documentation only. Phase 6D is not implemented in this update.
"""
    SYSTEM_GAP_DOC_PATH.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    args = parse_args()
    retrieval_rows = _load_jsonl(args.retrieval_results)
    api_rows = _load_jsonl(args.api_results)
    retrieval_summary = _load_json(args.retrieval_summary)
    api_summary = _load_json(args.api_summary)
    bad_cases = _retrieval_bad_cases(retrieval_rows) + _api_bad_cases(api_rows)
    _write_jsonl(args.bad_cases, bad_cases)
    _write_qa_doc(retrieval_summary, api_summary)
    _write_bad_case_doc(bad_cases, retrieval_summary, api_summary)
    _write_system_gap_doc(retrieval_summary, api_summary)
    summary = {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "bad_case_count": len(bad_cases),
        "by_type": dict(Counter(str(case.get("bad_case_type")) for case in bad_cases)),
        "writes_chroma": False,
        "calls_llm": False,
    }
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")


if __name__ == "__main__":
    main()
