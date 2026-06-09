# Enterprise Knowledge Base Agent Overview

企业知识库 Agent 是一个面向内部知识问答、流程解释和工程支持的后端能力。它不是简单聊天机器人，而是由服务入口、Agent 编排、检索工具、模型 provider 和结构化响应共同组成。用户提交问题后，后端先完成参数校验和会话标识处理，再由 Agent 判断是否需要访问知识库。如果问题依赖内部制度、技术方案、接口说明或排障经验，Agent 会调用检索工具获取相关片段，再把检索结果作为上下文交给模型生成答案。

在工程实现上，企业知识库 Agent 应保留原有服务框架的通用能力，例如健康检查、通用 invoke、流式输出和 Agent registry。新增能力应以扩展方式接入，避免重写整个服务。这样既能保持 upstream 框架可维护，又能清楚说明新增模块的边界：企业知识库文档入库、向量检索、source tracing、retrieval debug 和统一业务查询。

Agent 工作流通常包括输入防护、检索路由、query rewrite、retrieval、answer synthesis 和 fallback。输入防护负责过滤空问题或不适合处理的问题；检索路由负责判断是否需要知识库；query rewrite 把口语化问题改写为更适合检索的查询；retrieval 返回 top-k chunks；answer synthesis 要求模型只基于可用上下文回答；fallback 在检索为空或证据不足时给出克制说明。

一个可维护的企业知识库 Agent 需要明确日志和调试信息。每次回答都应能追踪命中的文档、chunk id、score、top_k、embedding provider、collection name 和模型 provider。这样当答案不可靠时，开发者可以判断问题来自数据缺失、切分粒度、query rewrite、prompt 约束还是模型生成。该项目的重点是后端工程化、检索可解释和接口可复现，而不是训练大模型。

