# Chunking Validation

## Phase 6B-1 Goal

Phase 6B-1 converts parser-passed samples into normalized metadata records and a chunk manifest for later vector-store ingestion. This phase does not write Chroma, call an embedding model, call an LLM, or run QA evaluation.

## Normalization Design

Normalization creates one metadata record per parser-passed sample. Full normalized text is written only to local cache under `data/knowledge_base/normalized/`, which is ignored by Git. Manifests store aliases, hashes, counts, source ids, source urls, and parser metadata.

## Raw Text Policy

Raw files, normalized text cache, and full chunk bodies are not committed because they may be large, licensed, or local-only. The committed manifests keep source tracing without storing full copyrighted or private text.

## Chunk Strategy

- DOCX: paragraph-aware aggregation with overlap.
- PDF: page-marker and paragraph-aware aggregation for text-extractable samples.
- HTML and Markdown: heading-aware metadata when headings are present.
- JSON and YAML: schema/key-aware text representation and metadata.
- CSV: skipped when no parser-passed CSV sample is available.

## Metadata Fields

Each chunk stores `chunk_id`, `normalized_id`, `source_id`, `sample_id`, `doc_type`, `domain`, `language`, `title`, `section_path`, optional `source_url`, optional page range, hash, metadata-only preview, parser metadata, and `embedding_written=false` / `chroma_written=false`.

## Quality Summary

- Total chunks: 626
- Chunk char min/avg/max: 14 / 801.67 / 966
- Empty chunks: 0
- Missing metadata: 0
- Duplicate chunk hashes: 0
- Preview max chars: 61
- Quality pass: True

## Distribution By Format

| Format | Chunk Count |
| --- | ---: |
| docx | 317 |
| html | 90 |
| json | 2 |
| markdown | 19 |
| pdf | 182 |
| yaml | 16 |

## Current Limits

- HTML samples are normalized when parser validation marks them as pass or when the local ignored HTML cache exists for a cataloged sample and the committed manifest is stale.
- CSV, PPTX, and OCR are not forced when no parser-passed sample is available.
- No retrieval quality or answer quality claims are made in this phase.

## Phase 6B-2 Plan

Phase 6B-2 should review chunk quality, adjust chunk sizes or section metadata if needed, and prepare a controlled local-only ingestion dry-run. Chroma and embedding should remain disabled until explicitly approved.
