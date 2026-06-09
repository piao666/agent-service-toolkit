# Enterprise RAG Pipeline

RAG 数据流可以拆成 document -> chunk -> embedding -> vector store -> retrieval -> context -> answer。document 是原始知识材料，可以是 Markdown、TXT、DOCX 或 PDF。文档加载时要保留 source、title、doc_type、page 等 metadata，因为这些信息会在后续 source tracing 中被用户和开发者看到。没有 metadata 的检索结果很难排查来源，也不利于构建可信回答。

chunk 是将长文档切成适合检索和上下文拼接的小片段。默认 chunk_size 可以设置为 800，chunk_overlap 可以设置为 120。chunk 太大时，检索命中会包含过多无关内容；chunk 太小时，语义上下文可能不足。overlap 的作用是让相邻片段保留少量上下文，减少边界切断带来的信息丢失。每个 chunk 都应生成稳定 chunk_id，便于调试、去重和评估。

embedding 会把文本片段转换为向量。本项目默认使用本地 embedding 模型，避免把企业知识库文本发送到第三方 embedding API。本地 embedding provider 应能在离线环境中创建 client，模型路径通过配置指定。向量写入 Chroma 时，collection name 使用 enterprise_knowledge_base，persist directory 使用本地目录，例如 chroma_enterprise。

retrieval 阶段根据用户问题生成查询向量，从 Chroma 中返回 top-k 相关 chunks。检索结果至少包含 source、score、chunk_id、metadata、content_preview 和 page_content。score 用于观察命中强弱，source 用于解释答案依据，content_preview 用于快速检查是否命中正确材料。answer 阶段不应把检索结果当作不可见黑盒，而应把上下文、来源和调试字段一起纳入后端响应设计。

