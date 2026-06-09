# Enterprise Model Provider Policy

企业知识库 Agent 后端可以支持多个模型 provider，但主线应保持简单可复现。开发阶段推荐使用 DeepSeek 进行中文问答、Prompt 调试和低成本验证。DeepSeek 适合快速观察回答格式、fallback 文案、query rewrite 质量和多轮调用行为。只要默认 chat 模型可用，就能支撑本地后端开发。

Qwen/OpenAI-compatible provider 适合验证私有化或自托管推理服务接入。OpenAI-compatible 在这里表示协议兼容，例如提供类似 /v1/chat/completions 的接口，并不代表必须使用国外 API。后续如果接入本地或远程 vLLM Qwen endpoint，应记录 base url、model name、API key 占位符、超时参数和响应延迟。该能力属于推理服务接入，不是训练成果。

Embedding provider 与 chat provider 要分开设计。企业知识库文本可能包含内部流程、接口说明和排障经验，因此默认 embedding provider 应为 local。只有在明确允许的情况下，才可以把 demo 或公开文本发送到第三方 embedding API。对于私有知识库，默认本地 embedding 能降低数据外发风险，也更适合离线演示和工程复现。

Provider 配置应放在环境变量中，真实 key 只保存在本地 .env，不提交到版本库。.env.example 只能写占位符和示例配置。后端代码不应硬编码真实 key，也不应把 provider 失败写成模型能力问题。排障时应区分配置错误、网络错误、服务超时、模型返回异常和检索无命中，分别记录到 debug 或运行日志中。
