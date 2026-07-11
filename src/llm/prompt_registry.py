"""Phase 5: Prompt registry — structured prompts for each custom_graph node."""

from llm.schema import LLMMessage

# ── Query Classifier ──────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """You are an enterprise knowledge base query classifier.
Analyze the user query and output JSON with:
- intent: "technical_reference" | "project_inquiry" | "mixed" | "ambiguous" | "unsupported"
- confidence: 0.0-1.0
- reasoning: brief explanation
- recommended_corpus: "official_docs" | "internal_engineering_docs" | "dual"

Rules:
- "technical_reference": asks about external tools/docs (FastAPI, Chroma, LangGraph, etc.)
- "project_inquiry": asks about THIS project's architecture, decisions, phases, configuration
- "mixed": asks about both external and internal topics
- "ambiguous": unclear intent
- "unsupported": cannot be answered from available knowledge bases
"""


def build_classifier_prompt(query: str) -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content=CLASSIFIER_SYSTEM),
        LLMMessage(role="user", content=f"Classify this query:\n\n{query}"),
    ]


# ── Memory Rewriter ──────────────────────────────────────────────────

REWRITER_SYSTEM = """You rewrite user queries for better retrieval.
Add missing context, expand abbreviations, normalize technical terms.
Output JSON: {"rewritten_query": "...", "changes": "..."}"""


def build_rewriter_prompt(query: str, history: list[str] | None = None) -> list[LLMMessage]:
    ctx = ""
    if history:
        ctx = "Previous conversation:\n" + "\n".join(history[-3:]) + "\n\n"
    return [
        LLMMessage(role="system", content=REWRITER_SYSTEM),
        LLMMessage(role="user", content=f"{ctx}Rewrite for better retrieval:\n\n{query}"),
    ]


# ── Planner ──────────────────────────────────────────────────────────

PLANNER_SYSTEM = """You plan retrieval steps for a RAG system.
Output JSON: {"steps": [...], "retrieval_queries": [...], "reasoning": "..."}
Generate 1-3 focused retrieval queries that will find the needed information."""


def build_planner_prompt(query: str, intent: str) -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content=PLANNER_SYSTEM),
        LLMMessage(
            role="user", content=f"Intent: {intent}\nQuery: {query}\n\nPlan retrieval steps:"
        ),
    ]


# ── Answer Generator ─────────────────────────────────────────────────

GROUNDED_ANSWER_SYSTEM = """You are an enterprise RAG answer generator.
Generate a well-structured answer based ONLY on the provided retrieval context.
Output JSON:
{
  "answer_markdown": "...",
  "citations": [{"source_id": "...", "chunk_id": "...", "heading_path": "...", "quoted_evidence": "..."}],
  "used_sources": ["..."],
  "unsupported_claims": ["..."],
  "hallucination_risk": "none" | "low" | "medium" | "high"
}

CRITICAL RULES:
1. Every factual claim MUST cite a source from the provided context.
2. If context lacks sufficient evidence, state "证据不足" and set hallucination_risk accordingly.
3. Do NOT fabricate information not present in the context.
4. Citations must reference actual chunk_ids from the context.
"""


def build_answer_prompt(
    query: str,
    context_chunks: list[dict],
    memory_context: str = "",
) -> list[LLMMessage]:
    ctx_text = "\n\n---\n\n".join(
        f"[CHUNK:{c.get('chunk_id', '?')} | SOURCE:{c.get('source_id', '?')} | {c.get('heading_path', '')}]\n{c.get('text_preview', '')}"
        for c in context_chunks[:5]
    )
    memory_text = ""
    if memory_context:
        memory_text = (
            "\n\nApproved operating constraints (not citation evidence):\n" + memory_context
        )
    return [
        LLMMessage(role="system", content=GROUNDED_ANSWER_SYSTEM),
        LLMMessage(
            role="user",
            content=f"Query: {query}\n\nContext:\n{ctx_text}{memory_text}\n\nGenerate grounded answer:",
        ),
    ]
