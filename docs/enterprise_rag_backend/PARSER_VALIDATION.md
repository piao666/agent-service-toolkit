# Parser Validation

## Phase 6A-2 Goal

Phase 6A-2 validates a controlled multi-format parser path for the AI autonomous learning and large language model technology knowledge base. It does not chunk, embed, write Chroma, call an LLM, or start QA evaluation.

## Why Small Samples Only

Small samples keep the workflow reproducible and auditable. Full-site crawling or bulk document collection would introduce noisy pages, licensing ambiguity, unstable diffs, and large raw files that should not be committed.

## Sample Source Summary

- Total validation records: 23
- HTML records: 10
- Local DOCX records: 3
- Local PDF records: 3
- Raw course files are inspected in place and are not copied into the repository.

## Format Coverage

| Format | Sample Count | Parser | Status | Notes |
| --- | ---: | --- | --- | --- |
| DOCX | 3 | docx-zip-xml | pass | Local course metadata only |
| PDF text | 3 | pypdf/pdf-marker-metadata | pass | Metadata/text extractability check |
| HTML | 10 | html.parser | not_available | Seed pages only |
| Markdown | 1 | plain text | pass | Repo docs |
| JSON | 2 | json | pass | Schema files |
| YAML | 1 | yaml | pass | source_catalog |
| CSV | 1 | csv | not_available | Small structured sample |
| PPTX | 1 | python-pptx | not_available | Availability check |
| Scanned PDF/OCR | 1 | OCR tool | not_available | Availability check |

## Failure Records

| Sample | Format | Error Type | Error Summary |
| --- | --- | --- | --- |
| None | - | - | - |

## Raw File Policy

Raw DOCX, PDF, PPT/PPTX, HTML cache files, normalized text, Chroma databases, model weights, logs, and secrets are not committed. Manifests store only metadata, hashes, counts, parser status, and source aliases.

## Before Phase 6B

- Review failed or unavailable parser capabilities.
- Decide which small raw samples are allowed for local-only cache use.
- Confirm license and redistribution status before normalization.
- Keep local embedding and Chroma writes disabled until ingestion is explicitly started.
