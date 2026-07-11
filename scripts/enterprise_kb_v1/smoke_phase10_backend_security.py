"""Backend-only security and fail-closed runtime smoke checks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
REPORT = ROOT / "reports" / "enterprise_kb_v1" / "phase10_backend_security_smoke.json"
sys.path.insert(0, str(SRC))


def _check(name: str, passed: bool, detail: object = "") -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _mock_heavy_dependencies() -> list[str]:
    mocked: list[str] = []
    for module in (
        "agents",
        "agents.agents",
        "agents.github_mcp_agent",
        "agents.github_mcp_agent.github_mcp_agent",
        "langchain_mcp_adapters",
        "langchain_mcp_adapters.client",
        "langchain_mcp_adapters.sessions",
        "mcp.client.streamable_http",
    ):
        if module not in sys.modules:
            sys.modules[module] = MagicMock()
            mocked.append(module)
    return mocked


def main() -> int:
    from llm.base import BaseLLMProvider
    from llm.client import LLMClient
    from llm.errors import LLMProviderError
    from llm.schema import LLMMessage
    from long_term_memory.sqlite_store import LongTermMemoryStore
    from schema.schema import EnterpriseKBGraphAnswerRequest
    from session_memory.schema import MemoryTurn
    from session_memory.store import MemoryStore

    checks: list[dict[str, object]] = []

    class FailingProvider(BaseLLMProvider):
        @property
        def provider_name(self) -> str:
            return "qwen"

        def generate(self, messages, **kwargs):
            raise LLMProviderError(
                "qwen",
                "qwen-max",
                "provider_http_error",
                status_code=403,
                retryable=False,
            )

    message = [LLMMessage(role="user", content="test")]
    closed = LLMClient(provider="mock", allow_fallback=False)
    closed._provider_name = "qwen"
    closed._model = "qwen-max"
    closed._provider = FailingProvider(model="qwen-max")
    try:
        closed.generate(message)
        fail_closed = False
    except LLMProviderError:
        fail_closed = True
    checks.append(_check("provider_failure_is_fail_closed", fail_closed))

    opted_in = LLMClient(provider="mock", allow_fallback=True)
    opted_in._provider_name = "qwen"
    opted_in._model = "qwen-max"
    opted_in._provider = FailingProvider(model="qwen-max")
    fallback_response = opted_in.generate(message)
    checks.append(
        _check(
            "fallback_requires_explicit_opt_in",
            fallback_response.provider == "mock" and opted_in.last_fallback_used,
            opted_in.last_fallback_reason,
        )
    )

    saved_env = {
        name: os.environ.get(name)
        for name in ("USE_FAKE_MODEL", "QWEN_API_KEY", "DEEPSEEK_API_KEY")
    }
    try:
        os.environ["USE_FAKE_MODEL"] = "true"
        os.environ["QWEN_API_KEY"] = "not-a-real-key"
        os.environ["DEEPSEEK_API_KEY"] = "not-a-real-key"
        forced_mock = LLMClient()
        checks.append(
            _check(
                "use_fake_model_overrides_configured_providers",
                forced_mock.is_mock and forced_mock.provider_name == "mock",
            )
        )
    finally:
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    invalid_requests = (
        {"query": "x" * 4001},
        {"query": "ok", "session_id": "bad/session"},
        {"query": "ok", "project_id": "bad/project"},
    )
    rejected = 0
    for payload in invalid_requests:
        try:
            EnterpriseKBGraphAnswerRequest(**payload)
        except ValidationError:
            rejected += 1
    checks.append(
        _check(
            "request_schema_rejects_invalid_boundaries",
            rejected == len(invalid_requests),
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = LongTermMemoryStore(str(Path(temp_dir) / "ltm.sqlite"))
        candidate = store.create_candidate(content="Keep citations visible")
        rejected_once = store.reject_candidate(candidate["candidate_id"])
        rejected_twice = store.reject_candidate(candidate["candidate_id"])
        rejected_missing = store.reject_candidate("cand_missing")

        approved_candidate = store.create_candidate(content="Use qwen-max")
        memory = store.approve_candidate(approved_candidate["candidate_id"])
        disabled_once = bool(memory) and store.disable_memory(memory["memory_id"])
        disabled_twice = bool(memory) and store.disable_memory(memory["memory_id"])
        disabled_missing = store.disable_memory("mem_missing")
        checks.append(
            _check(
                "memory_lifecycle_rejects_invalid_transitions",
                rejected_once
                and not rejected_twice
                and not rejected_missing
                and disabled_once
                and not disabled_twice
                and not disabled_missing,
            )
        )

    memory_store = MemoryStore(max_sessions=2, max_turns_per_session=2)
    for session_id in ("s1", "s2", "s3"):
        memory_store.add_turn(session_id, MemoryTurn(query=session_id))
    for index in range(4):
        memory_store.add_turn("s3", MemoryTurn(query=f"turn-{index}"))
    checks.append(
        _check(
            "session_memory_is_bounded",
            len(memory_store.list_sessions()) == 2
            and memory_store.get("s1") is None
            and memory_store.get("s3") is not None
            and len(memory_store.get("s3").turns) == 2,
            memory_store.stats(),
        )
    )

    mocked = _mock_heavy_dependencies()
    try:
        from fastapi.testclient import TestClient

        from core.settings import settings
        from service.service import app

        original_auth = settings.AUTH_SECRET
        original_fake = settings.USE_FAKE_MODEL
        settings.AUTH_SECRET = None
        settings.USE_FAKE_MODEL = True
        try:
            client = TestClient(app)
            runtime_response = client.get("/api/enterprise-kb/runtime/config")
            runtime = runtime_response.json()
            mismatch_response = client.post(
                "/api/enterprise-kb/graph/answer",
                json={
                    "query": "test",
                    "llm_provider": "mock",
                    "model": "qwen-max",
                },
            )
        finally:
            settings.AUTH_SECRET = original_auth
            settings.USE_FAKE_MODEL = original_fake
    finally:
        for module in mocked:
            sys.modules.pop(module, None)

    serialized_runtime = json.dumps(runtime, ensure_ascii=False)
    checks.append(
        _check(
            "runtime_config_is_redacted_and_fake_mode_is_explicit",
            runtime_response.status_code == 200
            and runtime.get("default_provider") == "mock"
            and "api_key" not in serialized_runtime.lower()
            and "auth_secret" not in serialized_runtime.lower(),
            runtime,
        )
    )
    checks.append(
        _check(
            "provider_model_mismatch_is_rejected",
            mismatch_response.status_code == 422,
            mismatch_response.status_code,
        )
    )

    passed = all(bool(item["passed"]) for item in checks)
    payload = {
        "phase": "phase10_backend_security",
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": passed,
        "checks": checks,
    }
    REPORT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
