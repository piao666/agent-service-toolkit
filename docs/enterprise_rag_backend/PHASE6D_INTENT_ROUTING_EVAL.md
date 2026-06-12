# Phase 6D-1 Intent Routing Evaluation

## Goal

Phase 6D-1 establishes an offline evaluation loop for user intent routing. The goal is to decide which route a user input should take before retrieval, writing, chat, safety refusal, or a future business-tool router is considered.

This is a deterministic baseline for evaluation only.
It is not wired into production Agent routing yet.
No LLM is called.
No business system is called.
No API endpoint is called.
No Chroma write is performed.
No embedding model is loaded.

## Why Intent Routing Matters

Enterprise Agent + RAG systems should not send every user input to semantic retrieval. A query like "Transformer 的自注意力机制是什么？" should use knowledge-base retrieval, but a query like "查询订单号 A20240601001 的物流状态" needs a business-system route in a later design. A query like "继续" needs clarification, and an unsafe request should be refused before retrieval or action planning.

Intent routing reduces unnecessary retrieval, separates knowledge answering from operational actions, and makes high-risk misroutes measurable before production integration.

## Intent Labels

| Intent | Definition |
| --- | --- |
| `knowledge_lookup` | Technical or domain knowledge questions that should use RAG retrieval. |
| `exact_lookup` | Exact metadata or field lookup, such as chunk id, source id, document type, collection name, or manifest field checks. |
| `business_action` | Requests that would need a business system, such as creating records, updating status, sending notifications, or querying operational records. |
| `chit_chat` | Greeting, assistant identity, casual conversation, or emotional support. |
| `summarization_or_rewrite` | Summarization, rewriting, polishing, translation, drafting, or style conversion. |
| `unsupported` | Unsafe, unsupported, or inappropriate requests, including credential theft, permission bypass, attacks, fraud, and guaranteed financial prediction. |
| `clarification_needed` | Ambiguous references or follow-up utterances without enough context. |

## Route Definitions

| Intent | Route |
| --- | --- |
| `knowledge_lookup` | `rag_retrieval` |
| `exact_lookup` | `exact_or_metadata_lookup` |
| `business_action` | `business_tool_router` |
| `chit_chat` | `chat_response` |
| `summarization_or_rewrite` | `writing_or_summary` |
| `unsupported` | `refusal_or_safety` |
| `clarification_needed` | `ask_clarification` |

The business route is evaluation-only in this phase. It does not execute any operation.

## Case Design

The case file contains 84 JSONL rows, with 12 cases per intent. It covers Chinese, English, mixed-language inputs, short inputs, ambiguous inputs, metadata lookup, safety-sensitive requests, and multi-turn follow-up style queries.

Expected intent distribution:

| Intent | Count |
| --- | ---: |
| `knowledge_lookup` | 12 |
| `exact_lookup` | 12 |
| `business_action` | 12 |
| `chit_chat` | 12 |
| `summarization_or_rewrite` | 12 |
| `unsupported` | 12 |
| `clarification_needed` | 12 |

## Deterministic Baseline

The baseline in `scripts/run_phase6d_intent_eval.py` uses ordered regular-expression rules:

1. Safety and unsupported patterns.
2. Ambiguous reference patterns that require clarification.
3. Writing, summarization, translation, or polishing patterns.
4. Business action patterns.
5. Exact metadata lookup patterns.
6. Chat patterns.
7. Technical knowledge lookup patterns.
8. Fallback to `clarification_needed`.

The fallback intentionally avoids blindly routing uncertain inputs to retrieval.

## Evaluation Metrics

The script writes:

- `data/knowledge_base/evaluation/phase6d_intent_eval_results.jsonl`
- `data/knowledge_base/evaluation/phase6d_intent_eval_summary.json`
- `data/knowledge_base/evaluation/phase6d_intent_bad_cases.jsonl`

The summary includes case count, accuracy, macro F1, expected and predicted distributions, per-intent precision/recall/F1, confusion matrix, bad case count, and high-risk misroute count. It also records safety flags proving that this phase does not call LLMs, APIs, Chroma, production Agent code, or embedding models.

## Results

Current deterministic baseline results:

| Metric | Value |
| --- | ---: |
| Case count | 84 |
| Accuracy | 1.0 |
| Macro F1 | 1.0 |
| Bad case count | 0 |
| High-risk misroute count | 0 |

Predicted intent distribution:

| Intent | Count |
| --- | ---: |
| `knowledge_lookup` | 12 |
| `exact_lookup` | 12 |
| `business_action` | 12 |
| `chit_chat` | 12 |
| `summarization_or_rewrite` | 12 |
| `unsupported` | 12 |
| `clarification_needed` | 12 |

## Confusion Matrix Summary

All 84 evaluation cases matched their expected intent and route in the current curated baseline run.

| Expected | Predicted | Count |
| --- | --- | ---: |
| `knowledge_lookup` | `knowledge_lookup` | 12 |
| `exact_lookup` | `exact_lookup` | 12 |
| `business_action` | `business_action` | 12 |
| `chit_chat` | `chit_chat` | 12 |
| `summarization_or_rewrite` | `summarization_or_rewrite` | 12 |
| `unsupported` | `unsupported` | 12 |
| `clarification_needed` | `clarification_needed` | 12 |

## Bad Case Analysis

The current run produced no bad cases. This should be interpreted as the deterministic baseline fitting the curated Phase 6D-1 case set, not as proof of general production routing quality.

Future bad-case analysis should pay special attention to:

- Business action queries that look like knowledge questions.
- Exact metadata lookup queries that contain technical terms.
- Ambiguous follow-up questions that mention an interface or document without enough context.
- Unsafe requests phrased as research or testing.

## High-Risk Misroute Analysis

High-risk misroutes are tracked separately because some routing mistakes are more harmful than ordinary classification errors. The current high-risk count is 0.

High-risk pairs include:

- `business_action` predicted as `knowledge_lookup`.
- `unsupported` predicted as `business_action`.
- `unsupported` predicted as `knowledge_lookup`.
- `exact_lookup` predicted as `knowledge_lookup`.
- `clarification_needed` predicted as `knowledge_lookup`.
- `clarification_needed` predicted as `business_action`.

## Current Limits

This phase is an offline deterministic evaluation only. It does not prove that the production Agent can route user traffic. It does not measure answer quality, retrieval quality, provider quality, latency under service load, or end-to-end Agent behavior.

The rule baseline is intentionally transparent and easy to debug. It may overfit the curated case set and should be expanded with harder paraphrases, multilingual edge cases, adversarial phrasing, and real anonymized usage patterns before any production integration.

## Why This Phase Avoids Runtime Integration

The purpose of Phase 6D-1 is to define labels, routes, metrics, and high-risk failure modes before changing runtime behavior. Calling an LLM or endpoint would mix routing evaluation with provider quality and service availability. Writing Chroma or loading embedding models would mix intent routing with retrieval pipeline evaluation, which belongs to later Phase 6D work.

## Next Phases

Phase 6D-2 can use this intent split to separate semantic retrieval questions from exact lookup, business action, and clarification cases before embedding benchmark runs.

Phase 6D-3 can build on the same labels when designing hybrid retrieval, especially for exact metadata lookup and knowledge lookup routing.

Production Agent/API routing should only be considered after this evaluation baseline is manually reviewed and later end-to-end Phase 6D-6 evaluation is explicitly planned.
