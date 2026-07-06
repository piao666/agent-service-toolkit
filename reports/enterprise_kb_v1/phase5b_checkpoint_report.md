# Phase 5B v1.2 Checkpoint Report

**日期**: 2026-07-06
**状态**: PASS

---

## v1.2 修复摘要 (vs v1.1)

| 修复项 | v1.1 | v1.2 |
|--------|------|------|
| 端点验证方式 | 静态源码扫描 | 静态 + runtime mock route 注册 + TestClient |
| endpoint_registered | static=true 充当 runtime | 明确区分 static / runtime / testclient |
| runtime_route_check | skipped (langchain_core 缺失) | 通过 (mock 无关 agents，FastAPI router 真实注册) |
| TestClient | 未测试 | 200 OK, 15 fields |
| overall_pass 条件 | 不要求 runtime | 要求 runtime_registered=true + testclient_call_ok=true |
| ZIP 可复现性 | 缺 models.py | 包含 models.py + custom_graph + llm |

### Runtime 验证方案说明

`service.py` 的完整 import 链经过 agents -> MCP -> langgraph runtime，存在版本兼容问题。
但 `POST /api/enterprise-kb/graph/answer` 端点本身**不依赖**这些 agents 模块。

v1.2 采用 mock 策略：
1. Pre-register mock 替代无关 agents 模块（MCP adapters、github agent 等）
2. 导入真实的 FastAPI `app` 和 `router` 对象（route 注册在 decorator 阶段完成）
3. 遍历 `router.routes` 确认 `/api/enterprise-kb/graph/answer` 已注册 POST
4. 使用 `TestClient(app)` 发起真实 HTTP POST，验证 200 响应和 15 个字段

Mock 仅作用于无关模块，endpoint 函数 `enterprise_kb_graph_answer` 内部调用的
`custom_graph.graph.run_custom_graph` 和 `llm.client.LLMClient` 均为真实模块。

## 新增端点

| Method | Path | 用途 |
|--------|------|------|
| POST | `/api/enterprise-kb/graph/answer` | custom_graph 8 节点完整链路知识库问答 |

## Smoke 结果 (全部 5 个, 返回码全部 0)

| Smoke | 结果 |
|-------|:---:|
| LLM Provider (mock/qwen/deepseek) | 3/3 PASS |
| Custom Graph (10 imports + pipeline) | PASS |
| Citation Guard (positive + negative + empty) | 3/3 PASS |
| Grounded Answer (fixture + no-key fallback) | PASS |
| Phase 5B Graph API | PASS |

### Phase 5B 判定明细

| 层级 | 检查项 | 结果 |
|------|--------|:---:|
| Static | route_decorator_found | true |
| Static | async_def_found | true |
| Static | import_request_model | true |
| Static | import_response_model | true |
| Static | import_run_custom_graph | true |
| Static | import_llm_client | true |
| Static | **endpoint_static_check_pass** | **true (6/6)** |
| Runtime | route_found_in_router | true |
| Runtime | route_methods | ["POST"] |
| Runtime | has_post_method | true |
| Runtime | app_type | FastAPI |
| Runtime | router_type | APIRouter |
| Runtime | **endpoint_runtime_registered** | **true** |
| TestClient | status_code | 200 |
| TestClient | field_count | 15 |
| TestClient | has_answer_markdown | true |
| TestClient | has_citations | true |
| TestClient | has_total_latency_ms | true |
| TestClient | llm_mode | mock_extractive |
| TestClient | **testclient_call_ok** | **true** |
| | **overall_pass** | **true** |

## 验收

| # | 标准 | 状态 |
|---|------|:---:|
| 1 | 全部脚本 py_compile 通过 | ✅ |
| 2 | 全部 5 个 smoke 返回码为 0 | ✅ |
| 3 | schema.importable=true | ✅ |
| 4 | direct_call.all_fields_present=true | ✅ |
| 5 | mock_fallback.pass=true | ✅ |
| 6 | endpoint_static_check_pass=true (6/6) | ✅ |
| 7 | endpoint_runtime_registered=true | ✅ |
| 8 | POST method found=true | ✅ |
| 9 | testclient_call_ok=true (200, 15 fields) | ✅ |
| 10 | overall_pass=true | ✅ |
| 11 | 无 MCP/ToolRouter/embedding/Chroma | ✅ |

**Phase 5B v1.2: PASS.**
