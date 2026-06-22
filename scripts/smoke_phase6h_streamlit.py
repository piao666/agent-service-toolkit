from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_PATH = REPO_ROOT / "src" / "streamlit_app.py"
REQUIRED_FUNCTIONS = {
    "request_agent_api",
    "render_source_cards",
    "render_memory_debug",
    "render_retrieval_debug",
    "render_verifier_debug",
    "render_graph_debug",
}
REQUIRED_EXAMPLES = {
    "RAG 是什么？",
    "它有什么局限？",
    "那它适合什么场景？",
    "FastAPI 的 Request Body 如何定义？",
    "LoRA 有什么作用？",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.-]{20,}", re.IGNORECASE),
    re.compile(r"BEGIN (?:RSA )?PRIVATE KEY"),
)
LOCAL_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/](?:Users|Models|Woker)[\\/]", re.IGNORECASE)


def main() -> int:
    streamlit_file_exists = STREAMLIT_PATH.is_file()
    source = STREAMLIT_PATH.read_text(encoding="utf-8") if streamlit_file_exists else ""
    tree = ast.parse(source) if source else ast.Module(body=[], type_ignores=[])
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    string_literals = {
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    summary = {
        "streamlit_file_exists": streamlit_file_exists,
        "api_helper_exists": "request_agent_api" in functions,
        "source_renderer_exists": "render_source_cards" in functions,
        "memory_debug_renderer_exists": "render_memory_debug" in functions,
        "retrieval_debug_renderer_exists": "render_retrieval_debug" in functions,
        "verifier_debug_renderer_exists": "render_verifier_debug" in functions,
        "graph_debug_expander_exists": "Graph debug" in string_literals,
        "graph_debug_renderer_exists": (
            "render_graph_debug" in functions and "graph_debug" in string_literals
        ),
        "legacy_empty_graph_debug_message_exists": any(
            "legacy 模式下该字段可以为空" in value for value in string_literals
        ),
        "grounding_status_display_exists": "grounding_status" in string_literals,
        "example_questions_present": REQUIRED_EXAMPLES.issubset(string_literals),
        "no_api_key_literal": not any(pattern.search(source) for pattern in SECRET_VALUE_PATTERNS),
        "no_local_absolute_path": LOCAL_PATH_PATTERN.search(source) is None,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
    }
    required_checks = {
        "streamlit_file_exists",
        "api_helper_exists",
        "source_renderer_exists",
        "memory_debug_renderer_exists",
        "retrieval_debug_renderer_exists",
        "verifier_debug_renderer_exists",
        "graph_debug_expander_exists",
        "graph_debug_renderer_exists",
        "legacy_empty_graph_debug_message_exists",
        "grounding_status_display_exists",
        "example_questions_present",
        "no_api_key_literal",
        "no_local_absolute_path",
    }
    for key, value in summary.items():
        print(f"{key}={value}")

    passed = all(summary[key] is True for key in required_checks)
    passed = passed and REQUIRED_FUNCTIONS.issubset(functions)
    print(f"smoke_passed={passed}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
