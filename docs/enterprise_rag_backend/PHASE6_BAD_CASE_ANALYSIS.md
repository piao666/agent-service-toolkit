# Phase 6C Bad Case Analysis

## Scope

This report analyzes Phase 6C retrieval-only results and the skipped endpoint evaluation record. It does not modify retrieval logic, endpoint behavior, or Chroma contents.

## Corrected Conclusion

Retrieval-only evaluation completed on reviewed Chroma sample. API/Agent endpoint evaluation was skipped because local service was unavailable. No end-to-end Agent QA success is claimed.

## Summary

- bad_case_count: 16
- retrieval_case_count: 26
- api_eval_status: skipped
- api_case_count_run: 0

## Bad Case Types

| bad_case_type | count |
| --- | --- |
| api_error | 10 |
| doc_type_miss | 1 |
| keyword_miss | 3 |
| source_miss | 2 |

## Diagnosis Categories

- `source_miss`: expected source was absent from top-k retrieval.
- `doc_type_miss`: expected document type was absent from top-k retrieval.
- `keyword_miss`: expected keywords were absent from retrieved chunk text.
- `banned_source_returned`: a policy-excluded source was returned.
- `api_error`: endpoint evaluation was skipped or failed.
- `api_fallback`: endpoint returned a fallback response.
- `answer_missing_expected_keyword`: endpoint answer did not include expected keywords.
- `answer_source_miss`: endpoint sources did not include the expected source.

## Current Constraints

The current reviewed collection has limited sample coverage. Retrieval failures should be treated as corpus and pipeline feedback, not as production accuracy numbers.

## Embedding Limitations

The current local small Chinese embedding model is useful for a Chinese retrieval smoke test, but it is limited for mixed Chinese/English documents, English API documentation, code snippets, function names, class names, configuration fields, exact identifiers, order numbers, paths, and cross-language matching.

Future work should evaluate multilingual embeddings, code-aware embeddings, hybrid retrieval, English technical-document cases, and mixed-language QA cases. The current model should not be presented as a production-best embedding choice.

## Suggested Fixes

Prioritize inspecting high-frequency bad case types, then adjust source coverage, chunk boundaries, or query wording. Endpoint-specific issues should be rerun only after the local service and configured provider are confirmed available.
