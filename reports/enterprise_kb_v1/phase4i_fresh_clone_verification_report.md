# Phase 4I: Fresh Clone Verification Report

**日期**: 2026-07-06
**范围**: 轻量核验 — registry / gitignore / import smoke / script dry-run

---

## 1. Registry Path Check

| Registry | Total | Found | Missing | Status |
|----------|:-----:|:-----:|:-------:|--------|
| source_registry.yaml (official) | 27 | 24 | 3 | ⚠️ |
| internal_engineering_sources.yaml | 34 | 34 | 0 | ✅ |

### Official registry 缺失详情

| source_id | local_path | 原因 |
|-----------|-----------|------|
| internal_project_runtime_snapshot | data/.../project_runtime_snapshot/ | deprecated, enabled=false |
| qwen_official_openai_compatible_api | data/.../qwen_official_openai_compatible_api/ | url_status=needs_manual_review, 排除采集 |
| qwen_official_model_parameters | data/.../qwen_official_model_parameters/ | url_status=needs_manual_review, 排除采集 |

**结论**: 3 个缺失均为已知的 deprecated/excluded source，不影响运行时 retrieval。Internal registry 100% 完整。

## 2. Git Ignore Check

| Pattern | Covered |
|---------|:------:|
| storage/ | ✅ |
| models/ | ✅ |
| *.zip | ✅ |
| data/.../raw_sources/official_docs/ | ✅ |
| data/.../chunks/official_docs/ | ✅ |
| data/.../chunks/internal_engineering_docs/ | ✅ |
| data/.../internal_engineering_corpus/ | ✅ |
| data/.../manifests/phase4fh_internal_chunk_manifest.json | ✅ |

**结论**: 8/8 全部覆盖。Fresh clone 不会误提交运行时产物。

## 3. Import Smoke

| Module | Status |
|--------|--------|
| rag.config | pass |
| schema.models | pass |
| rag.corpus_router | pass |
| rag.official_docs_retriever.validate_runtime_config | pass (validate only, no model load) |

**结论**: 核心 RAG 模块可正常 import。

## 4. Script Dry-Run

| 指标 | 结果 |
|------|:---:|
| Total scripts | 30 |
| All exist | ✅ |
| All syntax OK | ✅ |

## 5. Known Limitations

1. **Import smoke 不覆盖 langchain 重型依赖**: `rag.retriever`, `rag.traceable_rag_answer` 等模块需要 langchain 全栈，本地未安装。已有 `rag.official_docs_retriever.validate_runtime_config()` 作为轻量替代验证点。
2. **Script dry-run 不执行 HPC 脚本主体**: 仅做语法检查（py_compile），不调用 SentenceTransformer/chromadb。
3. **Registry 的 3 个 missing 为已知 deprecated/excluded source**: 不影响 retrieval。

## 6. Final Verdict

| 检查项 | Pass |
|--------|:---:|
| Registry path (internal) | ✅ 34/34 |
| Registry path (official) | ⚠️ 24/27 (3 deprecated) |
| Git ignore | ✅ 8/8 |
| Import smoke | ✅ 4/4 |
| Script syntax | ✅ 30/30 |

**Phase 4I Fresh Clone Verification: 通过。**
