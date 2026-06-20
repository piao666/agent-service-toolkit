# Enterprise RAG Agent Graph

```mermaid
flowchart TD
    A[query_classifier] --> B{query_type}
    B -->|ambiguous_query| C[clarification_response]
    B -->|unsupported_query| D[safe_response]
    B -->|normal_query| E[memory_rewriter]
    E --> F[retriever]
    F --> G[ranker]
    G --> H[answer_generator]
    H --> I[evidence_verifier]
    I --> J[final_response]
    C --> J
    D --> J
```

The normal route covers semantic, metadata, code/API, citation-required, and session-scoped
follow-up queries. The graph is optional; `ENTERPRISE_AGENT_GRAPH_MODE=legacy` remains the default.
