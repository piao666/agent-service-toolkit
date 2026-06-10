# Corpus Design

## Goal

Phase 6 expands the knowledge base from a small demo set into a realistic AI autonomous
learning and large language model technology corpus. The corpus must be based on real source
materials: local course documents, official documentation, public paper metadata, technical
configuration files, tables, slides, and scanned PDFs.

This phase does not download large web documentation, download paper PDFs, write Chroma, or run
QA evaluation.

## Why Demo Markdown Is Not Enough

The earlier demo documents are useful for proving the retrieval path, source tracing, and API
behavior. They are too small and too clean for Phase 6 evaluation because they do not cover:

- Multiple document formats and parser behavior.
- Long documents with mixed headings, tables, formulas, and examples.
- Retrieval noise across overlapping domains.
- License, redistribution, and source provenance checks.
- Realistic latency and chunking tradeoffs.

The upgraded corpus therefore needs source cataloging and manifests before ingestion.

## Why Not Use a Real Enterprise Database

A real enterprise database may contain private, regulated, or business-sensitive content. Using it
would make the demo difficult to reproduce and risky to share. This project instead uses public
technical sources and local course files with metadata-only tracking where redistribution is not
allowed. The result remains realistic for a RAG backend while staying reusable and privacy-aware.

## Source Categories

- Local course materials: DOCX and PDF files inspected locally without copying content.
- Official documentation: curated seed pages from selected technical projects.
- Public papers: metadata-only records with per-paper license checks.
- Slides: PPT or PPTX material reserved for later parser validation.
- Tables and config files: CSV, JSON, and YAML examples reserved for structured parsing tests.
- Scanned PDFs: reserved for OCR pipeline planning and separate quality checks.

## Format Coverage Target

The target corpus should eventually cover DOCX, PDF, PPT/PPTX, HTML, Markdown, CSV, JSON/YAML, and
scanned PDF. Phase 6A-1 only creates the directory structure and manifests. Later phases can add
small samples after license and parsing checks.

## Web Documentation Policy

Official documentation sites must not be recursively mirrored. Full-site crawling creates noisy
chunks, unnecessary bandwidth, unstable diffs, and license ambiguity. It can also collect blogs,
community pages, generated indexes, anchors, and versioned duplicates that are poor retrieval
targets.

The policy is:

- Register every source in `source_catalog.yaml`.
- Use `mode: sample_only`.
- Limit `max_depth` to 1 or 2.
- Limit `max_pages` to 5 to 10.
- Use curated `seed_pages`.
- Use `include_patterns` and `exclude_patterns`.
- Prefer official documentation source repositories when available.

## Paper Policy

Public paper sources are registered as metadata-only in Phase 6A-1. PDF download is disabled until
each paper's license and redistribution terms are checked.

Required paper policy:

```yaml
license_status: per_paper_check_required
redistribution: manifest_only
fetch_policy:
  mode: metadata_only
  download_pdf: false
```

## Manifest Design

`source_catalog.yaml` defines source-level policy: source type, domain, language, format, entry URL,
local path placeholder, license status, redistribution status, priority, fetch policy, and notes.

`document_manifest.jsonl` records inspected local document metadata. It intentionally stores a
stable alias, size, extension, SHA-256, and parser counts. It does not store original local absolute
paths or document text.

`document_manifest.schema.json` defines document-level fields for future ingestion tracking.

`chunk_manifest.schema.json` defines future chunk-level fields, including chunk id, document id,
source id, chunk index, content hash, preview, metadata, embedding provider, vector store, and write
status. Phase 6A-1 does not generate chunks.

## Phase Split

Phase 6A-1:

- Create corpus directories.
- Register source catalog entries.
- Define document and chunk manifest schemas.
- Inspect local course DOCX/PDF metadata.
- Dry-run web source policies without downloading content.

Phase 6A-2:

- Download or copy only approved small samples.
- Validate parsers for DOCX, PDF, HTML, Markdown, tables, slides, and scanned PDF placeholders.
- Keep source provenance and license notes attached.

Phase 6B:

- Normalize documents and create chunks.
- Validate chunk metadata, previews, and source tracing.
- Run local embedding only after the sample corpus is approved.

Phase 6C:

- Build a reproducible QA evaluation set.
- Record retrieval hits, answer quality, latency, and failure types.
- Analyze bad cases without claiming unmeasured accuracy gains.

## Later Ingestion And Evaluation Plan

Later phases should ingest only approved documents into the local vector store, then run a measured
QA workflow. The QA table should include expected points, rewritten query, top_k, hit count, matched
source, answer, answer quality, latency, failure type, and fix action. No evaluation claim should be
made without reproducible inputs and recorded results.
