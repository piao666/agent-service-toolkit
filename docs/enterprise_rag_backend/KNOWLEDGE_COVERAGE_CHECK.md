# 知识库覆盖排查报告

## 检查范围
- 知识库目录: `data/knowledge_base/`
- 扫描文件数: 218
- 关键词数: 33
- 限制: 每文件 ≤5MB，仅文本格式 (md/txt/json/jsonl/yaml/csv/html)

## 关键词覆盖概览

| 关键词 | 文件数 | 命中数 | 是否覆盖 |
|--------|--------|--------|----------|
| FastAPI | 96 | 33925 | COVERED |
| Request Body | 70 | 10002 | COVERED |
| Pydantic | 80 | 2492 | COVERED |
| LoRA | 42 | 500 | COVERED |
| RAG | 130 | 5553 | COVERED |
| LangGraph | 77 | 3586 | COVERED |
| Chroma | 167 | 15256 | COVERED |
| embedding | 88 | 8944 | COVERED |
| DeepSeek | 62 | 1110 | COVERED |
| Qwen | 58 | 1509 | COVERED |
| Agent | 154 | 50225 | COVERED |
| Python | 78 | 2341 | COVERED |
| 机器学习 | 30 | 543 | COVERED |
| 深度学习 | 39 | 1845 | COVERED |
| NLP | 77 | 34196 | COVERED |
| Transformer | 75 | 2923 | COVERED |
| Attention | 52 | 786 | COVERED |
| 反向传播 | 47 | 1202 | COVERED |
| 微调 | 47 | 682 | COVERED |
| 推理 | 47 | 1409 | COVERED |
| 知识库 | 66 | 4579 | COVERED |
| 检索 | 61 | 9941 | COVERED |
| 分块 | 29 | 156 | COVERED |
| chunk | 94 | 59506 | COVERED |
| manifest | 76 | 1502 | COVERED |
| normalize | 64 | 3118 | COVERED |
| evaluation | 63 | 872 | COVERED |
| source_id | 95 | 43985 | COVERED |
| Streamlit | 37 | 643 | COVERED |
| depends | 42 | 366 | COVERED |
| dependency | 35 | 357 | COVERED |
| middleware | 49 | 712 | COVERED |
| router | 45 | 372 | COVERED |

## 重点结论

- **FastAPI**: 基本覆盖 (文件数=96, 命中=33925)。
- **Request Body**: 基本覆盖 (文件数=70, 命中=10002)。
- **LoRA**: 基本覆盖 (文件数=42, 命中=500)。
- **RAG**: 覆盖较好 (文件数=130, 命中=5553)，说明系统项目类问题覆盖较好。
- **Agent**: 覆盖较好 (文件数=154, 命中=50225)，说明系统项目类问题覆盖较好。
- **Chroma**: 覆盖较好 (文件数=167, 命中=15256)，说明系统项目类问题覆盖较好。

## 判断

如果 FastAPI / Request Body / Pydantic / LoRA 等命中很少或为 0，
则回答缺少来源支持主要是知识库覆盖不足，而非检索或 Agent 编排失败。

如果 RAG / Agent / Chroma 等命中较多，说明系统项目类问题覆盖较好。

## 后续建议

1. 补充 FastAPI / Request Body / Pydantic 相关知识库资料。
2. 补充 LoRA / 微调 / QLoRA 相关中文资料。
3. 补充 DeepSeek / Qwen 等模型调用方式资料。
4. 考虑添加 corpus expansion 流程。