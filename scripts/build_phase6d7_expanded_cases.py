#!/usr/bin/env python3
"""Phase 6D-7: 构建 240 条 expanded evaluation cases (12 类 × 20 条)。

生成策略（不调用 LLM）：
  1. 复用 Phase 6D-4 的 72 条 reranker cases
  2. 从 agent_api cases 移植同 query_type 的额外 queries
  3. 手写 harder variants（同义词、参数变化、多约束）
  4. 新增 multi_hop_lookup / ambiguous_query / citation_required_query 各 20 条

输出: data/knowledge_base/evaluation/phase6d7_expanded_cases.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
OUTPUT_PATH = EVAL_DIR / "phase6d7_expanded_cases.jsonl"

# ── 现有 case 来源 ──────────────────────────────────────────────
RERANKER_CASES = EVAL_DIR / "phase6d_reranker_cases.jsonl"
AGENT_API_CASES = EVAL_DIR / "phase6d_agent_api_cases.jsonl"

# ── 知识库 source_id 清单 ────────────────────────────────────────
SOURCES = {
    "deep_learning": "local_deep_learning_course_docx",
    "nlp": "local_nlp_course_docx",
    "ai_agent": "local_ai_agent_course_pdf",
    "fastapi": "fastapi_docs",
    "repo": "repo_project_files",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """加载 JSONL 文件。"""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """写入 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def make_case(
    case_id: str,
    query: str,
    query_type: str,
    expected_source_id: str | None,
    expected_doc_type: str,
    expected_keywords: list[str],
    expected_exact_terms: list[str],
    is_negative: bool,
    banned_source_ids: list[str],
    notes: str,
    should_have_evidence: bool = True,
    should_answer: bool = True,
    requires_exact_match: bool = False,
) -> dict[str, Any]:
    """创建一条标准评估 case。"""
    return {
        "case_id": case_id,
        "query": query,
        "query_type": query_type,
        "expected_source_id": expected_source_id,
        "expected_doc_type": expected_doc_type,
        "expected_keywords": expected_keywords,
        "expected_exact_terms": expected_exact_terms,
        "requires_exact_match": requires_exact_match,
        "should_have_evidence": should_have_evidence,
        "should_answer": should_answer,
        "is_negative": is_negative,
        "banned_source_ids": banned_source_ids,
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════
# 手写扩展 cases — 基于知识库实际内容构造 harder queries
# ═══════════════════════════════════════════════════════════════════

# T01: zh_knowledge — 中文深度学习/NLP 知识 (基础8条来自reranker, 补充12条)
ZH_KNOWLEDGE_EXTRA = [
    make_case("exp_009", "SFT 和预训练的区别是什么？各自的训练目标有什么不同？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["微调", "SFT", "预训练", "监督"], [], False, [], "扩展: 对比型中文知识查询"),
    make_case("exp_010", "Transformer 中的多头注意力为什么比单头更好？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["多头注意力", "Transformer", "单头", "表示"], [], False, [], "扩展: 原理深度追问"),
    make_case("exp_011", "批归一化和层归一化的数学公式分别是什么，各适用于什么场景？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["批归一化", "层归一化", "BatchNorm", "LayerNorm"], [], False, [], "扩展: 对比+公式"),
    make_case("exp_012", "Adam 优化器中 beta1 和 beta2 参数分别控制什么？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["Adam", "beta1", "beta2", "优化器"], [], False, [], "扩展: 参数级追问"),
    make_case("exp_013", "自注意力中 Q、K、V 三个矩阵的计算流程是怎样的？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["Q", "K", "V", "自注意力", "矩阵"], [], False, [], "扩展: 计算流程追问"),
    make_case("exp_014", "BERT 的预训练任务为什么选择 MLM 和 NSP？NSP 后来为什么被移除？",
              "zh_knowledge", SOURCES["nlp"], "docx",
              ["BERT", "MLM", "NSP", "预训练"], [], False, [], "扩展: 设计决策追问"),
    make_case("exp_015", "对比学习中的 InfoNCE loss 如何计算正负样本相似度？",
              "zh_knowledge", SOURCES["nlp"], "docx",
              ["对比学习", "InfoNCE", "正样本", "负样本"], [], False, [], "扩展: 损失函数深度追问"),
    make_case("exp_016", "RLHF 训练流程中 reward model 和 policy model 分别怎么更新？",
              "zh_knowledge", SOURCES["ai_agent"], "pdf",
              ["RLHF", "reward", "policy", "PPO"], [], False, [], "扩展: 多模型训练流程"),
    make_case("exp_017", "LoRA 微调中 rank 参数的大小对模型效果和训练速度有什么影响？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["LoRA", "rank", "微调", "低秩"], [], False, [], "扩展: 超参数影响分析"),
    make_case("exp_018", "梯度裁剪为什么能防止梯度爆炸？clip_value 应该如何设置？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["梯度裁剪", "梯度爆炸", "clip"], [], False, [], "扩展: 训练技巧追问"),
    make_case("exp_019", "数据增强在 NLP 任务中有哪些常用方法？各自的优缺点是什么？",
              "zh_knowledge", SOURCES["nlp"], "docx",
              ["数据增强", "NLP", "回译", "替换"], [], False, [], "扩展: 方法论对比"),
    make_case("exp_020", "模型量化中 INT8 和 INT4 的精度损失分别有多大？什么场景可以接受？",
              "zh_knowledge", SOURCES["deep_learning"], "docx",
              ["量化", "INT8", "INT4", "精度"], [], False, [], "扩展: 部署优化追问"),
]

# T02: en_api_doc — 英文 API 文档查询
EN_API_DOC_EXTRA = [
    make_case("exp_029", "How does FastAPI handle dependency injection for path parameters vs query parameters?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["dependency injection", "path parameters", "query parameters"], [], False, [], "扩展: DI 深度追问"),
    make_case("exp_030", "What is the difference between Depends() and yield dependencies in FastAPI?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["Depends", "yield", "dependency"], [], False, [], "扩展: yield 对比"),
    make_case("exp_031", "How do you configure CORS middleware for specific origins in FastAPI?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["CORS", "middleware", "origins"], [], False, [], "扩展: 中间件配置"),
    make_case("exp_032", "What status codes does FastAPI return for validation errors by default?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["status codes", "validation errors", "422"], [], False, [], "扩展: 错误处理"),
    make_case("exp_033", "How do you implement WebSocket endpoints with FastAPI?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["WebSocket", "endpoints", "WebSocketDisconnect"], [], False, [], "扩展: WebSocket"),
    make_case("exp_034", "How does FastAPI generate OpenAPI schema for response models with Optional fields?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["OpenAPI", "response model", "Optional"], [], False, [], "扩展: Schema生成"),
    make_case("exp_035", "What is the purpose of APIRouter prefix and tags parameters?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["APIRouter", "prefix", "tags"], [], False, [], "扩展: Router配置"),
    make_case("exp_036", "How do you test FastAPI endpoints with TestClient and dependency overrides?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["TestClient", "dependency overrides", "pytest"], [], False, [], "扩展: 测试方法"),
    make_case("exp_037", "How does FastAPI handle background tasks vs Celery for async operations?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["background tasks", "Celery", "BackgroundTasks"], [], False, [], "扩展: 异步任务对比"),
    make_case("exp_038", "Explain Pydantic v2 model_validate vs model_dump in FastAPI request handling.",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["Pydantic", "model_validate", "model_dump", "v2"], [], False, [], "扩展: Pydantic v2"),
    make_case("exp_039", "How do you implement rate limiting with FastAPI middleware?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["rate limiting", "middleware", "throttling"], [], False, [], "扩展: 限流"),
    make_case("exp_040", "How do you handle file upload with progress tracking in FastAPI?",
              "en_api_doc", SOURCES["fastapi"], "html",
              ["file upload", "UploadFile", "progress"], [], False, [], "扩展: 文件上传"),
]

# T03: mixed_zh_en_api — 中英混合 API 查询
MIXED_ZH_EN_API_EXTRA = [
    make_case("exp_049", "FastAPI 的 lifespan 事件和 @app.on_event 有什么区别？什么场景用哪个？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["lifespan", "on_event", "startup", "shutdown"], [], False, [], "扩展: 生命周期"),
    make_case("exp_050", "如何在 FastAPI 中使用 OAuth2PasswordBearer 实现 JWT 认证？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["OAuth2PasswordBearer", "JWT", "认证"], [], False, [], "扩展: 认证"),
    make_case("exp_051", "Pydantic BaseModel 中的 validator 和 field_validator 在 v1/v2 中有什么区别？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["validator", "field_validator", "Pydantic", "v1", "v2"], [], False, [], "扩展: 版本差异"),
    make_case("exp_052", "FastAPI middleware 的 order 如何影响 request/response 处理流程？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["middleware", "order", "request", "response"], [], False, [], "扩展: 中间件顺序"),
    make_case("exp_053", "如何用 FastAPI 实现 SSE (Server-Sent Events) 的流式返回？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["SSE", "Server-Sent Events", "StreamingResponse"], [], False, [], "扩展: 流式"),
    make_case("exp_054", "FastAPI 的 response_model 和 response_model_exclude 如何在序列化时协同工作？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["response_model", "exclude", "序列化"], [], False, [], "扩展: 序列化"),
    make_case("exp_055", "如何在 FastAPI 中集成 Prometheus metrics 监控端点？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["Prometheus", "metrics", "监控"], [], False, [], "扩展: 监控"),
    make_case("exp_056", "FastAPI 的 sub-dependency 和 dependency override 在测试中如何使用？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["sub-dependency", "override", "测试"], [], False, [], "扩展: 依赖测试"),
    make_case("exp_057", "FastAPI 项目中如何组织大型 router 结构？APIRouter 的 include_router 怎么用？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["router", "include_router", "大型项目"], [], False, [], "扩展: 代码组织"),
    make_case("exp_058", "如何使用 FastAPI + SQLAlchemy async session 实现数据库事务管理？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["SQLAlchemy", "async session", "事务"], [], False, [], "扩展: 数据库集成"),
    make_case("exp_059", "FastAPI Swagger UI 中如何自定义参数描述和示例值？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["Swagger", "参数描述", "示例", "Field"], [], False, [], "扩展: 文档定制"),
    make_case("exp_060", "Pydantic 的 computed_field 和 model_computed_fields 在 FastAPI 响应中如何使用？",
              "mixed_zh_en_api", SOURCES["fastapi"], "html",
              ["computed_field", "Pydantic", "响应"], [], False, [], "扩展: 计算字段"),
]

# T04: agent_rag_concept — Agent/RAG 概念 (原始只有8条在reranker, 补充12条)
AGENT_RAG_EXTRA = [
    make_case("exp_069", "Agent 的 Plan-and-Execute 模式和 ReAct 模式各自的适用场景是什么？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["Plan-and-Execute", "ReAct", "Agent"], [], False, [], "扩展: Agent架构对比"),
    make_case("exp_070", "RAG 系统中 chunk size 和 overlap 如何影响检索质量和推理速度？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["chunk size", "overlap", "检索", "RAG"], [], False, [], "扩展: 分块策略"),
    make_case("exp_071", "Multi-Agent 系统中 agent 之间如何通过共享记忆通信？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["Multi-Agent", "共享记忆", "通信"], [], False, [], "扩展: 多Agent协作"),
    make_case("exp_072", "Tool-use Agent 如何实现工具的动态注册和发现？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["Tool-use", "动态注册", "工具发现"], [], False, [], "扩展: 工具机制"),
    make_case("exp_073", "RAG 系统中 reranker 和 embedding model 如何协同工作？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["reranker", "embedding", "协同", "RAG"], [], False, [], "扩展: Reranker集成"),
    make_case("exp_074", "LangGraph 中 checkpoint 和 interrupt 如何实现人机协同审批流程？",
              "agent_rag_concept", SOURCES["repo"], "json",
              ["LangGraph", "checkpoint", "interrupt", "审批"], [], False, [], "扩展: 人机协同"),
    make_case("exp_075", "Agent 评估中使用 LLM-as-Judge 有哪些局限性？如何缓解？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["LLM-as-Judge", "评估", "局限性"], [], False, [], "扩展: 评估方法"),
    make_case("exp_076", "RAG 系统中 hybrid search 的 dense 和 sparse 权重如何调优？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["hybrid search", "dense", "sparse", "权重"], [], False, [], "扩展: 混合搜索"),
    make_case("exp_077", "Agent 系统中的 guardrail 和 safety filter 应该在哪个阶段介入？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["guardrail", "safety", "filter"], [], False, [], "扩展: 安全机制"),
    make_case("exp_078", "Function-calling Agent 如何处理 tool 返回结果过长的问题？",
              "agent_rag_concept", SOURCES["ai_agent"], "pdf",
              ["Function-calling", "tool", "截断"], [], False, [], "扩展: 工具调用"),
    make_case("exp_079", "知识库中 manifest 和 content cache 的关系是怎样的？各自解决什么问题？",
              "agent_rag_concept", SOURCES["repo"], "json",
              ["manifest", "content cache", "知识库"], [], False, [], "扩展: KB架构"),
    make_case("exp_080", "LangGraph agent 的 node 和 edge 设计模式有哪些最佳实践？",
              "agent_rag_concept", SOURCES["repo"], "json",
              ["LangGraph", "node", "edge", "设计模式"], [], False, [], "扩展: 工作流设计"),
]

# T05: exact_metadata_lookup — 精确元数据查询
EXACT_METADATA_EXTRA = [
    make_case("exp_089", "local_nlp_course_docx 中有哪些章节标题？",
              "exact_metadata_lookup", SOURCES["nlp"], "docx",
              ["章节", "标题", "NLP"], [], False, [], "扩展: 文档结构查询"),
    make_case("exp_090", "chunk_manifest.jsonl 中 doc_type 为 pdf 的 chunk 有多少个？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["chunk_manifest", "doc_type", "pdf"], [], False, [], "扩展: 统计查询"),
    make_case("exp_091", "哪些文档的 source_type 是 local_course？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["source_type", "local_course"], [], False, [], "扩展: 类型筛选"),
    make_case("exp_092", "repo_project_files 中有哪些 Python 文件？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["Python", "repo_project_files", ".py"], [], False, [], "扩展: 文件类型查询"),
    make_case("exp_093", "fastapi_docs 中包含 middleware 关键词的 chunk 有哪些？",
              "exact_metadata_lookup", SOURCES["fastapi"], "html",
              ["middleware", "fastapi_docs"], [], False, [], "扩展: 关键词+来源"),
    make_case("exp_094", "source_catalog.yaml 中 domain 字段有哪些取值？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["source_catalog", "domain"], [], False, [], "扩展: schema查询"),
    make_case("exp_095", "哪些 chunk 的 language 标记为 zh？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["language", "zh"], [], False, [], "扩展: 语言筛选"),
    make_case("exp_096", "chunk_id 以 'chunk_fastapi_' 开头的第一个 chunk 内容是什么？",
              "exact_metadata_lookup", SOURCES["fastapi"], "html",
              ["chunk_id", "fastapi"], [], False, [], "扩展: ID前缀查询"),
    make_case("exp_097", "local_deep_learning_course_docx 中有多少个 size 为 large 的 chunk？",
              "exact_metadata_lookup", SOURCES["deep_learning"], "docx",
              ["size", "large", "chunk"], [], False, [], "扩展: chunk属性"),
    make_case("exp_098", "哪些文档同时包含 Code 和 Markdown 类型的 chunk？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["Code", "Markdown", "chunk类型"], [], False, [], "扩展: 多类型查询"),
    make_case("exp_099", "normalized_manifest.jsonl 中 document_id 的前缀分布是怎样的？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["normalized_manifest", "document_id", "前缀"], [], False, [], "扩展: ID分布查询"),
    make_case("exp_100", "chunk_quality_report.json 中 quality_score 低于 0.5 的 chunk 有哪些？",
              "exact_metadata_lookup", SOURCES["repo"], "json",
              ["quality_score", "chunk_quality_report"], [], False, [], "扩展: 质量筛选"),
]

# T06: code_api_config — 代码/API 配置查询
CODE_API_CONFIG_EXTRA = [
    make_case("exp_109", "pyproject.toml 中 dependencies 和 dev-dependencies 分别有哪些包？",
              "code_api_config", SOURCES["repo"], "json",
              ["pyproject.toml", "dependencies"], [], False, [], "扩展: 依赖查询"),
    make_case("exp_110", "CHROMA_COLLECTION_NAME 在哪个文件中定义？默认值是什么？",
              "code_api_config", SOURCES["repo"], "json",
              ["CHROMA_COLLECTION_NAME", "config.py"], [], False, [], "扩展: 配置追踪"),
    make_case("exp_111", "enterprise_tools.py 中 MAX_TOP_K 和 CONTEXT_TOTAL_CHAR_LIMIT 的值分别是多少？",
              "code_api_config", SOURCES["repo"], "json",
              ["MAX_TOP_K", "CONTEXT_TOTAL_CHAR_LIMIT"], [], False, [], "扩展: 常量值查询"),
    make_case("exp_112", "langgraph.json 中 graphs 字段配置了哪些 graph？",
              "code_api_config", SOURCES["repo"], "json",
              ["langgraph.json", "graphs"], [], False, [], "扩展: graph配置"),
    make_case("exp_113", "docker-compose.yml 中定义了哪些 service 和 port 映射？",
              "code_api_config", SOURCES["repo"], "json",
              ["docker-compose", "service", "port"], [], False, [], "扩展: Docker配置"),
    make_case("exp_114", ".env 文件中默认的 EMBEDDING_PROVIDER 和 LLM_PROVIDER 是什么？",
              "code_api_config", SOURCES["repo"], "json",
              ["EMBEDDING_PROVIDER", "LLM_PROVIDER"], [], False, [], "扩展: 环境变量"),
    make_case("exp_115", "vector_store.py 中 Chroma 的 PersistenceClient 是如何创建和配置的？",
              "code_api_config", SOURCES["repo"], "json",
              ["PersistenceClient", "Chroma", "vector_store"], [], False, [], "扩展: Chroma配置"),
    make_case("exp_116", "run_phase6d7 相关的脚本入口参数有哪些？batch_size 的默认值是什么？",
              "code_api_config", SOURCES["repo"], "json",
              ["run_phase6d7", "batch_size", "argparse"], [], False, [], "扩展: 脚本参数"),
    make_case("exp_117", "项目中 LOCAL_EMBEDDING_MODEL_ROOT 环境变量在哪些文件中被引用？",
              "code_api_config", SOURCES["repo"], "json",
              ["LOCAL_EMBEDDING_MODEL_ROOT", "环境变量"], [], False, [], "扩展: 变量追踪"),
    make_case("exp_118", "enterprise_rag_agent.py 中 LangGraph workflow 包含哪些 node？",
              "code_api_config", SOURCES["repo"], "json",
              ["LangGraph", "node", "workflow"], [], False, [], "扩展: 工作流结构"),
    make_case("exp_119", "run_service.py 启动时的 host 和 port 默认值是什么？uvicorn 使用了哪些配置？",
              "code_api_config", SOURCES["repo"], "json",
              ["uvicorn", "host", "port", "run_service"], [], False, [], "扩展: 服务配置"),
    make_case("exp_120", "task.txt 文件中的 Phase 6D-7 相关内容有哪些？",
              "code_api_config", SOURCES["repo"], "json",
              ["task.txt", "Phase 6D-7"], [], False, [], "扩展: 任务追踪"),
]

# T07: short_keyword — 短关键词查询
SHORT_KEYWORD_EXTRA = [
    make_case("exp_129", "Attention",
              "short_keyword", SOURCES["deep_learning"], "docx",
              ["Attention", "注意力"], [], False, [], "扩展: 英文关键词"),
    make_case("exp_130", "Embedding",
              "short_keyword", SOURCES["nlp"], "docx",
              ["Embedding", "嵌入"], [], False, [], "扩展: 英文关键词"),
    make_case("exp_131", "Fine-tuning",
              "short_keyword", SOURCES["deep_learning"], "docx",
              ["Fine-tuning", "微调"], [], False, [], "扩展: 英文关键词"),
    make_case("exp_132", "API Router",
              "short_keyword", SOURCES["fastapi"], "html",
              ["Router", "API"], [], False, [], "扩展: API关键词"),
    make_case("exp_133", "Dependency",
              "short_keyword", SOURCES["fastapi"], "html",
              ["Dependency"], [], False, [], "扩展: 单关键词"),
    make_case("exp_134", "向量检索",
              "short_keyword", SOURCES["ai_agent"], "pdf",
              ["向量", "检索"], [], False, [], "扩展: 中文关键词"),
    make_case("exp_135", "模型推理",
              "short_keyword", SOURCES["deep_learning"], "docx",
              ["推理", "模型"], [], False, [], "扩展: 中文关键词"),
    make_case("exp_136", "Chunking",
              "short_keyword", SOURCES["repo"], "json",
              ["Chunking"], [], False, [], "扩展: 技术关键词"),
    make_case("exp_137", "ReAct",
              "short_keyword", SOURCES["ai_agent"], "pdf",
              ["ReAct"], [], False, [], "扩展: 单术语"),
    make_case("exp_138", "Normalization",
              "short_keyword", SOURCES["nlp"], "docx",
              ["Normalization", "归一化"], [], False, [], "扩展: 英文术语"),
    make_case("exp_139", "QKV",
              "short_keyword", SOURCES["deep_learning"], "docx",
              ["Q", "K", "V", "注意力"], [], False, [], "扩展: 缩写关键词"),
    make_case("exp_140", "MCP",
              "short_keyword", SOURCES["ai_agent"], "pdf",
              ["MCP"], [], False, [], "扩展: 协议缩写"),
]

# T08: negative_banned_source — 负向 banned 测试
NEGATIVE_BANNED_EXTRA = [
    make_case("exp_149", "请解释 Kubernetes 中的 Pod 调度策略",
              "negative_banned_source", None, "docx",
              ["Kubernetes", "Pod", "kube"], [],
              True, ["kubernetes_docs", "kubernetes_cn_docs"], "扩展: 明确banned源"),
    make_case("exp_150", "PyTorch DataLoader 多进程加载数据的原理是什么？",
              "negative_banned_source", None, "docx",
              ["DataLoader", "PyTorch", "多进程"], [],
              True, ["pytorch_docs"], "扩展: 第三方库banned"),
    make_case("exp_151", "Give me a step-by-step guide to deploy with LangGraph Cloud",
              "negative_banned_source", None, "md",
              ["LangGraph Cloud"], [], True, ["langgraph_docs"], "扩展: 英文banned"),
    make_case("exp_152", "ChromaDB collection 的 metadata 过滤语法怎么写？",
              "negative_banned_source", None, "md",
              ["ChromaDB", "metadata", "filter"], [],
              True, ["chroma_docs"], "扩展: Chroma banned"),
    make_case("exp_153", "如何在 HPC 集群上配置 SLURM 作业调度？",
              "negative_banned_source", None, "md",
              ["SLURM", "HPC"], [],
              True, ["kubernetes_docs", "kubernetes_cn_docs"], "扩展: 非KB内容"),
    make_case("exp_154", "介绍一下 TensorFlow 2.x 的 tf.function 装饰器",
              "negative_banned_source", None, "md",
              ["TensorFlow", "tf.function"], [],
              True, ["pytorch_docs"], "扩展: 竞品banned"),
    make_case("exp_155", "Docker Compose 的 depends_on 和 healthcheck 如何配合使用？",
              "negative_banned_source", None, "md",
              ["Docker Compose", "depends_on", "healthcheck"], [],
              True, ["langgraph_docs", "kubernetes_docs"], "扩展: 基础设施banned"),
    make_case("exp_156", "如何使用 AWS SageMaker 部署模型端点？",
              "negative_banned_source", None, "md",
              ["SageMaker", "AWS", "模型部署"], [],
              True, ["chroma_docs", "pytorch_docs", "langgraph_docs"], "扩展: 云服务banned"),
    make_case("exp_157", "什么是 Redis 集群的哨兵模式和高可用架构？",
              "negative_banned_source", None, "md",
              ["Redis", "哨兵", "高可用"], [],
              True, ["chroma_docs", "kubernetes_docs"], "扩展: 数据库banned"),
    make_case("exp_158", "请帮我写一个 React useEffect 的示例代码",
              "negative_banned_source", None, "md",
              ["React", "useEffect"], [],
              True, ["pytorch_docs", "langgraph_docs"], "扩展: 前端banned"),
    make_case("exp_159", "如何配置 Nginx 反向代理实现 HTTPS 终止？",
              "negative_banned_source", None, "md",
              ["Nginx", "反向代理", "HTTPS"], [],
              True, ["chroma_docs"], "扩展: 运维banned"),
    make_case("exp_160", "gRPC 和 REST API 在微服务通信中各有什么优缺点？",
              "negative_banned_source", None, "md",
              ["gRPC", "REST", "微服务"], [],
              True, ["langgraph_docs", "chroma_docs"], "扩展: 协议banned"),
]

# T09: phase6c_bad_case_regression — 回归测试 (基础8条 + bad cases + 新hard cases)
BAD_CASE_REGRESSION_EXTRA = [
    make_case("exp_169", "PyTorch 训练模型通常包括哪些步骤？",
              "phase6c_bad_case_regression", SOURCES["deep_learning"], "docx",
              ["训练", "PyTorch", "步骤", "数据加载"], [], False, [], "回归: qa_006 bad case"),
    make_case("exp_170", "RAG 在 Agent 系统中如何降低幻觉风险？",
              "phase6c_bad_case_regression", SOURCES["ai_agent"], "pdf",
              ["RAG", "幻觉", "Agent", "知识库"], [], False, [], "回归: qa_017 bad case"),
    make_case("exp_171", "manifest 如何支持入库前审查？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["manifest", "审查", "入库"], [], False, [], "回归: qa_023 bad case"),
    make_case("exp_172", "为什么 Phase 6B-2 不应该评估问答准确率？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["Phase 6B-2", "评估", "准确率"], [], False, [], "回归: qa_024 bad case"),
    make_case("exp_173", "chunk_manifest 中的 review_status 字段有哪些可能取值？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["review_status", "approved", "rejected"], [], False, [], "回归: chunk schema"),
    make_case("exp_174", "Phase 6D-4 中 Qwen3-Reranker 和 bge-reranker-base 的 latency 差异原因？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["Qwen3-Reranker", "bge-reranker", "latency"], [], False, [], "回归: 性能分析"),
    make_case("exp_175", "embedding_benchmark_summary 中 best_models 的评选标准是什么？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["best_models", "embedding", "benchmark"], [], False, [], "回归: 评估指标"),
    make_case("exp_176", "CMakeLists.txt 中如何配置 CUDA 编译选项？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["CMakeLists", "CUDA"], [], False, [], "回归: 构建配置"),
    make_case("exp_177", "本地嵌入模型和云端 API 嵌入在准确性上有什么差异？什么场景选哪种？",
              "phase6c_bad_case_regression", SOURCES["ai_agent"], "pdf",
              ["嵌入", "本地模型", "云端API", "准确性"], [], False, [], "回归: 模型选择权衡"),
    make_case("exp_178", "知识库检索中 exact match 和 semantic match 应该如何平衡权��？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["exact match", "semantic match", "权重", "hybrid"], [], False, [], "回归: 检索策略"),
    make_case("exp_179", "Phase 5 中调试 LLM provider 时遇到的 Token 耗尽和 API 调用失败是怎么解决的？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["Phase 5", "provider", "Token", "API"], [], False, [], "回归: 调试历史"),
    make_case("exp_180", "chunk_quality_report 中的 completeness 和 relevance 指标如何计算？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["chunk_quality", "completeness", "relevance"], [], False, [], "回归: 质量指标"),
    make_case("exp_180a", "为什么 tokenizer_config.json 中 model_max_length 设置会影响 chunking 结果？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["tokenizer", "model_max_length", "chunking"], [], False, [], "回归: tokenizer与chunking交互"),
    make_case("exp_180b", "Phase 6C 中 QA evaluation 发现 retrieval 失败的根本原因是什么？有哪些改进措施？",
              "phase6c_bad_case_regression", SOURCES["repo"], "json",
              ["Phase 6C", "QA", "retrieval", "改进"], [], False, [], "回归: 根因分析"),
]

# T10: multi_hop_lookup — 跨文档链式查询 (全新 20 条)
MULTI_HOP_LOOKUP = [
    make_case("exp_181", "RAGFlow 默认使用什么分块策略？这个策略在 AI Engineering Hub 中是如何被评价的？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["RAGFlow", "分块", "Chunking"], [], False, [], "multi-hop: RAGFlow + AEH"),
    make_case("exp_182", "DeepSeek-R1 使用的蒸馏方法是什么？Tiny-LLM 项目中有没有类似的技术实践？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["蒸馏", "DeepSeek", "Tiny-LLM"], [], False, [], "multi-hop: 跨模型对比"),
    make_case("exp_183", "vLLM 如何处理 KV cache？Flash Attention 提出了什么替代方案？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["KV cache", "vLLM", "Flash Attention"], [], False, [], "multi-hop: 推理优化"),
    make_case("exp_184", "LLaMA 架构中 RoPE 的作用是什么？ALiBi 相比 RoPE 有什么不同？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["RoPE", "ALiBi", "LLaMA", "位置编码"], [], False, [], "multi-hop: 位置编码对比"),
    make_case("exp_185", "QLoRA 的 4-bit 量化如何减少显存？和标准 LoRA 在训练吞吐上有多少差异？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["QLoRA", "4-bit", "LoRA", "显存"], [], False, [], "multi-hop: QLoRA+LoRA对比"),
    make_case("exp_186", "FastAPI 的 Depends 和 LangGraph 的 StateGraph 中的 dependency 管理有什么异同？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["Depends", "StateGraph", "dependency", "FastAPI", "LangGraph"], [], False, [], "multi-hop: 跨框架对比"),
    make_case("exp_187", "在 RAG 系统中，Sentence-BERT 的 embedding 和 BM25 的 sparse retrieval 分别解决了什么问题？两者如何互补？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["Sentence-BERT", "BM25", "embedding", "sparse"], [], False, [], "multi-hop: 检索方法"),
    make_case("exp_188", "LLM 推理中的 speculative decoding 和 KV cache compression 分别是什么原理？哪种对长文本更有效？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["speculative decoding", "KV cache", "推理"], [], False, [], "multi-hop: 推理加速对比"),
    make_case("exp_189", "知识库 review pipeline 中 chunk manifest 如何驱动 normalization？两者之间的数据流是怎样的？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["chunk manifest", "normalization", "review", "pipeline"], [], False, [], "multi-hop: KB数据流"),
    make_case("exp_190", "MoE 在 transformer 中最早由哪篇论文提出？Switch Transformer 和 Mixtral 分别在 MoE 上做了哪些改进？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["MoE", "Switch Transformer", "Mixtral"], [], False, [], "multi-hop: MoE演进"),
    make_case("exp_191", "LLM 评估中 BLEU 和 ROUGE 的局限性是什么？基于 embedding 的 BERTScore 如何改进？",
              "multi_hop_lookup", SOURCES["nlp"], "docx",
              ["BLEU", "ROUGE", "BERTScore", "评估"], [], False, [], "multi-hop: 评估指标演进"),
    make_case("exp_192", "数据清洗 pipeline 中的去重和归一化分别用什么工具？Phase 6B-1 中选择了哪种方案？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["去重", "归一化", "Phase 6B-1", "pipeline"], [], False, [], "multi-hop: 数据处理"),
    make_case("exp_193", "什么是 DPO 和 RLHF 的区别？在 agent-service-toolkit 项目中是否有相关的实现参考？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["DPO", "RLHF", "对齐"], [], False, [], "multi-hop: 对齐方法"),
    make_case("exp_194", "检索评估中 Recall@k 和 MRR 分别衡量什么？为什么只用 Recall 不够？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["Recall@k", "MRR", "检索评估"], [], False, [], "multi-hop: 评估指标"),
    make_case("exp_195", "如何进行 RAG 检索的 A/B 测试？评估中需要控制的变量有哪些？",
              "multi_hop_lookup", SOURCES["ai_agent"], "pdf",
              ["A/B测试", "RAG", "变量控制"], [], False, [], "multi-hop: 实验设计"),
    make_case("exp_196", "Transformer 的训练中 warmup steps 和学习率衰减如何配合？cosine schedule 相比 linear 有什么优势？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["warmup", "学习率", "cosine", "schedule"], [], False, [], "multi-hop: 调参策略"),
    make_case("exp_197", "知识库检索中的 hybrid search 和 agent 中的 multi-tool retrieval 在架构上有什么不同？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["hybrid search", "multi-tool", "retrieval"], [], False, [], "multi-hop: 检索架构"),
    make_case("exp_198", "上下文窗口扩展方法（RoPE interpolation vs. PI）的原理区别是什么？各有什么优缺点？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["RoPE", "interpolation", "PI", "上下文"], [], False, [], "multi-hop: 长文本方法"),
    make_case("exp_199", "大模型部署中 ONNX Runtime 和 TensorRT-LLM 在 GPU 推理时各有什么优劣势？",
              "multi_hop_lookup", SOURCES["deep_learning"], "docx",
              ["ONNX", "TensorRT", "推理", "GPU"], [], False, [], "multi-hop: 部署框架"),
    make_case("exp_200", "评估集中的 negative_banned_source 和 phase6c_bad_case_regression 类型的 case 设计有什么不同目的？",
              "multi_hop_lookup", SOURCES["repo"], "json",
              ["negative_banned_source", "bad_case", "评估"], [], False, [], "multi-hop: 评估设计"),
]

# T11: ambiguous_query — 故意模糊/开放查询 (全新 20 条)
AMBIGUOUS_QUERY = [
    make_case("exp_201", "什么是最好的模型？",
              "ambiguous_query", None, "docx",
              ["模型"], [], False, [], "ambiguous: 极度模糊"),
    make_case("exp_202", "怎么用 RAG？",
              "ambiguous_query", SOURCES["ai_agent"], "pdf",
              ["RAG"], [], False, [], "ambiguous: 模糊工具使用"),
    make_case("exp_203", "介绍一下 Transformer",
              "ambiguous_query", SOURCES["deep_learning"], "docx",
              ["Transformer"], [], False, [], "ambiguous: 广泛话题"),
    make_case("exp_204", "学习率设多少？",
              "ambiguous_query", SOURCES["deep_learning"], "docx",
              ["学习率"], [], False, [], "ambiguous: 缺少上下文"),
    make_case("exp_205", "GPU 怎么选？",
              "ambiguous_query", SOURCES["deep_learning"], "docx",
              ["GPU"], [], False, [], "ambiguous: 硬件选择"),
    make_case("exp_206", "部署需要注意什么？",
              "ambiguous_query", SOURCES["ai_agent"], "pdf",
              ["部署"], [], False, [], "ambiguous: 开放性问题"),
    make_case("exp_207", "那个文档在哪里？",
              "ambiguous_query", None, "md",
              ["文档"], [], False, [], "ambiguous: 指代不明"),
    make_case("exp_208", "这个参数怎么调？",
              "ambiguous_query", None, "docx",
              ["参数"], [], False, [], "ambiguous: 无明确指标"),
    make_case("exp_209", "效果不好怎么办？",
              "ambiguous_query", None, "docx",
              ["效果"], [], False, [], "ambiguous: 无上下文"),
    make_case("exp_210", "有什么改进建议？",
              "ambiguous_query", None, "md",
              ["改进"], [], False, [], "ambiguous: 开放性问题"),
    make_case("exp_211", "对比一下那几个方法",
              "ambiguous_query", None, "docx",
              ["对比", "方法"], [], False, [], "ambiguous: 无明确方法名"),
    make_case("exp_212", "这个错误怎么解决？",
              "ambiguous_query", None, "md",
              ["错误"], [], False, [], "ambiguous: 无错误详情"),
    make_case("exp_213", "配置应该怎么改？",
              "ambiguous_query", SOURCES["repo"], "json",
              ["配置"], [], False, [], "ambiguous: 无具体文件"),
    make_case("exp_214", "怎样才能更快？",
              "ambiguous_query", None, "docx",
              ["更快"], [], False, [], "ambiguous: 目标不明确"),
    make_case("exp_215", "API 怎么调用？",
              "ambiguous_query", SOURCES["fastapi"], "html",
              ["API"], [], False, [], "ambiguous: 无具体API名"),
    make_case("exp_216", "最新版本有什么变化？",
              "ambiguous_query", None, "md",
              ["版本", "变化"], [], False, [], "ambiguous: 无项目名"),
    make_case("exp_217", "token 不够用怎么办？",
              "ambiguous_query", SOURCES["deep_learning"], "docx",
              ["token"], [], False, [], "ambiguous: token含义不明"),
    make_case("exp_218", "评估怎么做？",
              "ambiguous_query", SOURCES["repo"], "json",
              ["评估"], [], False, [], "ambiguous: 无评估对象"),
    make_case("exp_219", "和论文里的一样吗？",
              "ambiguous_query", None, "md",
              ["论文"], [], False, [], "ambiguous: 无具体论文"),
    make_case("exp_220", "这个好用吗？",
              "ambiguous_query", None, "md",
              [], [], False, [], "ambiguous: 主观问题"),
]

# T12: citation_required_query — 要求引用 (全新 20 条)
CITATION_REQUIRED = [
    make_case("exp_221", "根据 Flash Attention 论文，它的三个关键创新是什么？",
              "citation_required_query", SOURCES["deep_learning"], "docx",
              ["Flash Attention", "创新", "IO-aware"], [], False, [], "citation: Flash Attention"),
    make_case("exp_222", "Datawhale happy-llm 教程中关于 RoPE 的实现是怎么描述的？请给出具体章节。",
              "citation_required_query", SOURCES["nlp"], "docx",
              ["RoPE", "happy-llm", "Datawhale"], [], False, [], "citation: 教程引用"),
    make_case("exp_223", "引用 AI Engineering Hub 中对 RAG 评估方法的描述",
              "citation_required_query", SOURCES["ai_agent"], "pdf",
              ["AI Engineering Hub", "RAG评估"], [], False, [], "citation: AEH引用"),
    make_case("exp_224", "根据 source_catalog.yaml，知识库中包含哪些 domain？每个 domain 有哪些 source？",
              "citation_required_query", SOURCES["repo"], "json",
              ["source_catalog", "domain"], [], False, [], "citation: 元数据引用"),
    make_case("exp_225", "chunk_manifest.jsonl 中关于 review_status 的定义是怎样的？引用 schema 文件中的说明。",
              "citation_required_query", SOURCES["repo"], "json",
              ["chunk_manifest", "review_status", "schema"], [], False, [], "citation: Schema引用"),
    make_case("exp_226", "关于 LoRA 微调的最佳 rank 选择，deep_learning 课程文档中给出了什么建议？",
              "citation_required_query", SOURCES["deep_learning"], "docx",
              ["LoRA", "rank", "建议"], [], False, [], "citation: 课程文档"),
    make_case("exp_227", "FastAPI 官方文档中关于 middleware 执行顺序的说明是什么？",
              "citation_required_query", SOURCES["fastapi"], "html",
              ["middleware", "执行顺序", "FastAPI"], [], False, [], "citation: 官方文档"),
    make_case("exp_228", "引用 task.txt 中关于 Phase 6D-4 benchmark 结果的描述",
              "citation_required_query", SOURCES["repo"], "json",
              ["Phase 6D-4", "benchmark", "task.txt"], [], False, [], "citation: 项目文档"),
    make_case("exp_229", "PyTorch 官方文档中关于 DataLoader num_workers 的最佳设置建议是什么？",
              "citation_required_query", SOURCES["deep_learning"], "docx",
              ["DataLoader", "num_workers", "PyTorch"], [], False, [], "citation: 官方文档"),
    make_case("exp_230", "引用 NLP 教程中关于 Transformer 架构的解释，包括 encoder 和 decoder 的区别。",
              "citation_required_query", SOURCES["nlp"], "docx",
              ["Transformer", "encoder", "decoder"], [], False, [], "citation: 教程引用"),
    make_case("exp_231", "chunk_quality_report.json 中 quality_score 的计算公式是什么？引用相关文档说明。",
              "citation_required_query", SOURCES["repo"], "json",
              ["quality_score", "公式", "chunk_quality"], [], False, [], "citation: 质量公式"),
    make_case("exp_232", "根据 LLaMA-Factory 文档，7B 模型 LoRA 训练的最低 GPU 显存要求是多少？",
              "citation_required_query", SOURCES["deep_learning"], "docx",
              ["LLaMA-Factory", "LoRA", "7B", "GPU"], [], False, [], "citation: 硬件要求"),
    make_case("exp_233", "引用 Agent 课程中关于 human-in-the-loop 设计模式的描述",
              "citation_required_query", SOURCES["ai_agent"], "pdf",
              ["human-in-the-loop", "Agent"], [], False, [], "citation: 设计模式"),
    make_case("exp_234", "FastAPI 的 lifespan 设计相对于 @app.on_event 的优势是什么？引用文档中的对比说明。",
              "citation_required_query", SOURCES["fastapi"], "html",
              ["lifespan", "on_event", "对比"], [], False, [], "citation: 版本对比"),
    make_case("exp_235", "在 Phase 6D-2 embedding benchmark 中，哪个 query_type 的 source_hit 最低？引用 summary 数据。",
              "citation_required_query", SOURCES["repo"], "json",
              ["Phase 6D-2", "embedding", "source_hit"], [], False, [], "citation: 评估结果"),
    make_case("exp_236", "根据 DeepSeek-V2 论文，MLA (Multi-head Latent Attention) 相比标准 MHA 减少了多少 KV cache？",
              "citation_required_query", SOURCES["deep_learning"], "docx",
              ["MLA", "MHA", "KV cache", "DeepSeek"], [], False, [], "citation: 论文数据"),
    make_case("exp_237", "引用 chunk_manifest.schema.json 中 requires_exact_match 字段的定义",
              "citation_required_query", SOURCES["repo"], "json",
              ["schema", "requires_exact_match"], [], False, [], "citation: 字段定义"),
    make_case("exp_238", "multilingual-e5-base 在 Phase 6D-4 benchmark 中的 MRR 是多少？引用 summary 数据。",
              "citation_required_query", SOURCES["repo"], "json",
              ["multilingual-e5-base", "MRR", "Phase 6D-4"], [], False, [], "citation: 模型指标"),
    make_case("exp_239", "根据 tokenizer_config.json，bge-small-zh-v1.5 使用的 tokenizer 类型和 vocab_size 是多少？",
              "citation_required_query", SOURCES["repo"], "json",
              ["tokenizer_config", "bge-small", "vocab_size"], [], False, [], "citation: 模型配置"),
    make_case("exp_240", "引用 pyproject.toml 中关于 sentence-transformers 和 transformers 的版本约束",
              "citation_required_query", SOURCES["repo"], "json",
              ["pyproject.toml", "sentence-transformers", "transformers"], [], False, [], "citation: 依赖版本"),
]


def build_expanded_cases() -> list[dict[str, Any]]:
    """构建完整的 240 条 expanded cases。"""
    all_cases: list[dict[str, Any]] = []
    seen_queries: set[str] = set()

    # ── Step 1: 从 reranker cases 加载基础 72 条 ──
    reranker_cases = load_jsonl(RERANKER_CASES)
    id_counter = 0

    # 按 query_type 分组 reranker cases
    type_order = [
        "zh_knowledge", "en_api_doc", "mixed_zh_en_api",
        "agent_rag_concept", "exact_metadata_lookup", "code_api_config",
        "short_keyword", "negative_banned_source", "phase6c_bad_case_regression",
    ]
    type_cases: dict[str, list[dict[str, Any]]] = {t: [] for t in type_order}
    for c in reranker_cases:
        qt = c.get("query_type", "")
        if qt in type_cases:
            type_cases[qt].append(c)

    # ── Step 2: 从 agent_api cases 加载额外 queries ──
    api_cases = load_jsonl(AGENT_API_CASES)
    api_by_type: dict[str, list[dict[str, Any]]] = {t: [] for t in type_order}
    for c in api_cases:
        qt = c.get("query_type", "")
        if qt in api_by_type:
            api_by_type[qt].append(c)

    # ── Step 3: 各类型的额外 queries (手写) ──
    extra_by_type: dict[str, list[dict[str, Any]]] = {
        "zh_knowledge": ZH_KNOWLEDGE_EXTRA,
        "en_api_doc": EN_API_DOC_EXTRA,
        "mixed_zh_en_api": MIXED_ZH_EN_API_EXTRA,
        "agent_rag_concept": AGENT_RAG_EXTRA,
        "exact_metadata_lookup": EXACT_METADATA_EXTRA,
        "code_api_config": CODE_API_CONFIG_EXTRA,
        "short_keyword": SHORT_KEYWORD_EXTRA,
        "negative_banned_source": NEGATIVE_BANNED_EXTRA,
        "phase6c_bad_case_regression": BAD_CASE_REGRESSION_EXTRA,
    }

    # ── Step 4: 合并每个类型 20 条 ──
    for t in type_order:
        cases_for_type: list[dict[str, Any]] = []
        # 4a: 基础 8 条来自 reranker
        for c in type_cases[t][:8]:
            cases_for_type.append(c)
        # 4b: 补充来自 agent_api (去重 query)
        added_from_api = 0
        for c in api_by_type.get(t, []):
            if added_from_api >= 5:
                break
            if c["query"] not in seen_queries:
                cases_for_type.append(c)
                seen_queries.add(c["query"])
                added_from_api += 1
        # 4c: 填充剩余到手写扩展 (不检查 seen_queries, 手工cases不会重复)
        extra = extra_by_type.get(t, [])
        needed = 20 - len(cases_for_type)
        for c in extra[:needed]:
            cases_for_type.append(c)
            seen_queries.add(c["query"])
        # 4d: 如果还不够，用 reranker 剩下的
        if len(cases_for_type) < 20:
            remaining = type_cases[t][8:]
            for c in remaining:
                if len(cases_for_type) >= 20:
                    break
                if c["query"] not in seen_queries:
                    cases_for_type.append(c)
                    seen_queries.add(c["query"])

        # 截断到 20
        cases_for_type = cases_for_type[:20]

        # 重新编号
        for c in cases_for_type:
            id_counter += 1
            c["case_id"] = f"exp_{id_counter:03d}"
            if "phase" in c:
                del c["phase"]
            if "evaluation_focus" in c:
                del c["evaluation_focus"]
            if "source_case_id" in c:
                del c["source_case_id"]
            # 确保新字段存在
            c.setdefault("should_have_evidence", True)
            c.setdefault("should_answer", not c.get("is_negative", False))
            if "requires_exact_match" not in c:
                c["requires_exact_match"] = False
            seen_queries.add(c["query"])

        all_cases.extend(cases_for_type)

    # ── Step 5: 追加 3 个新类型各 20 条 (T10-T12) ──
    new_types = [
        ("multi_hop_lookup", MULTI_HOP_LOOKUP),
        ("ambiguous_query", AMBIGUOUS_QUERY),
        ("citation_required_query", CITATION_REQUIRED),
    ]
    for tname, cases_list in new_types:
        for c in cases_list:
            id_counter += 1
            c["case_id"] = f"exp_{id_counter:03d}"
            all_cases.append(c)

    return all_cases


def validate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """校验 cases 的完整性和分布。"""
    from collections import Counter

    report: dict[str, Any] = {"total": len(cases), "type_distribution": {}, "issues": []}

    type_counts: Counter = Counter()
    for c in cases:
        qt = c.get("query_type", "unknown")
        type_counts[qt] += 1
        # 检查必填字段
        for field in ["case_id", "query", "query_type", "expected_keywords"]:
            if field not in c:
                report["issues"].append(f"{c.get('case_id', '?')}: missing {field}")
        # 检查 case_id 格式
        cid = c.get("case_id", "")
        if not cid.startswith("exp_"):
            report["issues"].append(f"{cid}: invalid case_id format")

    report["type_distribution"] = dict(type_counts)

    # 验证 12 类每类 20 条
    expected_types = {
        "zh_knowledge", "en_api_doc", "mixed_zh_en_api",
        "agent_rag_concept", "exact_metadata_lookup", "code_api_config",
        "short_keyword", "negative_banned_source", "phase6c_bad_case_regression",
        "multi_hop_lookup", "ambiguous_query", "citation_required_query",
    }
    for t in expected_types:
        count = type_counts.get(t, 0)
        if count != 20:
            report["issues"].append(f"{t}: expected 20, got {count}")

    report["valid"] = len(report["issues"]) == 0 and report["total"] == 240
    return report


def main() -> None:
    print("Building Phase 6D-7 expanded evaluation cases...")
    cases = build_expanded_cases()

    print(f"Generated {len(cases)} cases")

    report = validate_cases(cases)
    print(f"Validation: {'PASS' if report['valid'] else 'FAIL'}")
    print(f"Type distribution:")
    for t, c in sorted(report["type_distribution"].items()):
        print(f"  {t}: {c}")

    if report["issues"]:
        print(f"Issues ({len(report['issues'])}):")
        for i in report["issues"][:10]:
            print(f"  - {i}")

    write_jsonl(OUTPUT_PATH, cases)
    print(f"Written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
