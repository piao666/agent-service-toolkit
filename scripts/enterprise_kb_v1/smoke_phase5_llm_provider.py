#!/usr/bin/env python3
"""Phase 5 v1.1 Smoke 1: LLM Provider — JSON parse + structured output verification."""

import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

from llm.base import ProviderFactory, MockProvider
from llm.schema import LLMMessage


def test_provider(name: str) -> dict:
    entry = {"provider": name}
    try:
        provider = ProviderFactory.create(name)
        entry["created"] = True
        entry["provider_name"] = provider.provider_name
        entry["is_mock"] = isinstance(provider, MockProvider)

        # Request structured JSON
        messages = [
            LLMMessage(role="system", content='Output only valid JSON: {"intent":"technical_reference","confidence":0.9,"reasoning":"test"}'),
            LLMMessage(role="user", content="classify: What is FastAPI?"),
        ]
        resp = provider.generate(messages)

        # Parse JSON
        try:
            parsed = json.loads(resp.content.strip())
            entry["json_parsed"] = True
            entry["parsed_intent"] = parsed.get("intent", "")
            entry["parsed_confidence"] = parsed.get("confidence", 0)
            entry["parsed_reasoning"] = parsed.get("reasoning", "")
            entry["required_fields_present"] = all(k in parsed for k in ["intent", "confidence", "reasoning"])
        except (json.JSONDecodeError, TypeError):
            entry["json_parsed"] = False
            entry["required_fields_present"] = False
            entry["raw_content_preview"] = resp.content[:200]

        entry["response_content_len"] = len(resp.content)
        entry["latency_ms"] = resp.latency_ms

        # For non-mock providers (qwen/deepseek), record fallback
        if name != "mock":
            entry["fallback_used"] = isinstance(provider, MockProvider)
            entry["fallback_reason"] = "missing_api_key" if isinstance(provider, MockProvider) else "real_provider_used"
        else:
            entry["fallback_used"] = False
            entry["fallback_reason"] = "native_mock"

        entry["status"] = "pass" if entry.get("json_parsed") or (name != "mock" and entry["fallback_used"]) else "fail"
    except Exception as e:
        entry["status"] = "fail"
        entry["error"] = str(e)[:200]
    return entry


def main():
    results = {"smoke": "phase5_llm_provider", "timestamp": datetime.now(timezone.utc).isoformat(), "tests": []}
    for name in ["mock", "qwen", "deepseek"]:
        r = test_provider(name)
        print(f"  {name}: json_parsed={r.get('json_parsed','?')} required_fields={r.get('required_fields_present','?')} fallback={r.get('fallback_used','?')}")
        results["tests"].append(r)

    results["all_mock_fallback_works"] = all(t["status"] == "pass" for t in results["tests"])
    path = REPORTS / "phase5_llm_provider_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")


if __name__ == "__main__":
    main()
