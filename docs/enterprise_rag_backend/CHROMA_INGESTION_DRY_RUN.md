# Chroma Ingestion Dry Run

## Phase 6B-2 Goal

Phase 6B-2 verifies a small local-only Chroma ingestion path for reviewed corpus chunks. It does not call an LLM, does not use `/enterprise/agent/query`, and does not run QA evaluation.

## Candidate Scope

Only chunks with all of the following fields are eligible:

- `normalization_status=pass`
- `review_status=approved`
- `ingest_candidate=true`

The dry run excludes `needs_review`, `rejected`, `filtered`, and known non-candidate web samples such as navigation-heavy or redirect pages. This prevents reviewed-out material from becoming retrieval evidence.

## Small Limit First

The first execution uses a small `--limit` such as 80 chunks. This keeps local embedding and Chroma writes easy to inspect before expanding coverage in a later phase.

## Chroma Settings

- `persist_dir`: `chroma_enterprise_phase6`
- `collection_name`: `enterprise_ai_learning_kb_reviewed`

This avoids overwriting the earlier `chroma_enterprise` directory and `enterprise_knowledge_base` collection.

## Embedding

Embedding uses the local provider configured by `EMBEDDING_PROVIDER=local` and `LOCAL_EMBEDDING_MODEL_PATH`. Reports use the alias `local_bge_small_zh_v1_5` instead of a local absolute path. Document text is read from ignored local normalized cache and is not sent to an external embedding API.

## Commands

Dry-run planning:

```powershell
python scripts\ingest_phase6_chroma.py --dry-run --limit 80
```

Small local ingestion:

```powershell
python scripts\ingest_phase6_chroma.py --execute --limit 80 --persist-dir chroma_enterprise_phase6 --collection-name enterprise_ai_learning_kb_reviewed
```

Retrieval checks:

```powershell
python scripts\test_phase6_chroma_retrieval.py --persist-dir chroma_enterprise_phase6 --collection-name enterprise_ai_learning_kb_reviewed --query "激活函数的作用是什么？" --top-k 5
python scripts\test_phase6_chroma_retrieval.py --persist-dir chroma_enterprise_phase6 --collection-name enterprise_ai_learning_kb_reviewed --query "FastAPI 请求体如何定义？" --top-k 5
```

## Generated Reports

- `data/knowledge_base/manifests/chroma_ingestion_manifest.jsonl`
- `data/knowledge_base/manifests/chroma_ingestion_report.json`

The local Chroma database is intentionally ignored by Git.

## Retrieval Validation Boundary

Phase 6B-2 only verifies vector-store ingestion scope and local retrieval mechanics. It does not perform QA evaluation, does not evaluate answer accuracy, and does not call an LLM.

The Kubernetes query is a banned-source exclusion test only. If it returns non-Kubernetes approved chunks, that confirms excluded sources were not ingested; it is not a semantic quality pass.

## Next Steps

Phase 6B-3 can broaden ingestion after reviewing the dry-run report and retrieval results. Phase 6C should handle QA evaluation and bad-case analysis after the approved corpus is stable.
