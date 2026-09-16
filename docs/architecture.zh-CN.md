# FinSage 架构

> English: see [`architecture.md`](architecture.md)

本文档概述 FinSage 的整体架构。全栈施工规格与 ADR 决策记录属内部工作文档，不随本仓库公开发布。

## 1. 设计原则

- **确定性优先于自主性。** 优先使用确定性函数/工作流，而非自主 Agent。财务算术始终由代码计算，绝不由 LLM 计算。
- **证据与审计内生。** 每个结论都可追溯到证据（含 `document_id` / `chunk_id` / 来源），每个节点都写入可审计记录。
- **冻结技术栈。** Milvus、MySQL、Redis、LangGraph、MCP、BGE-M3 与 BGE-Reranker-v2-M3 为架构承诺，未经 ADR + 显式批准不得替换。
- **诚实降级。** 当外部依赖未配置（Milvus、MySQL、需 token 的 Provider）时，相关能力直接停用——系统绝不伪造数据或指标来填补空缺。

## 2. 分层

```text
┌──────────────────────────── apps/web  Next.js + TS + Tailwind + shadcn/ui ────────────────────────────┐
│  路由外壳 · ResearchComposer · Answer/Evidence/Calculation/CitationMarker/Trace · SSE 客户端           │
│  （独立容器 finsage-web，容器化部署端口 3200）                                                          │
└───────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                            │ REST + SSE                       src/finsage/api  FastAPI
┌───────────────────────────────────────────┴───────────────────────────────────────────────────────────┐
│  api/         认证 · 路由 · SSE · 错误契约（FIN-XXXX）· 任务管理                                       │
│  agents/      LangGraph 工作流（4 张图：research_qa / financial_health / due_diligence / report）      │
│  workflows/   共享研究状态 · 检查点持久化                                                               │
│  governance/  政策门控 · 核验（V001–V008）· 置信度（六因子）· 审计                                     │
│  financial/   确定性金融引擎（增长、比率、估值、单位换算）                                              │
│  evaluation/  FinEval 数据集 · 评估器 · BenchmarkRunner                                                │
│  retrieval/   BGE-M3 稠密/稀疏 · 融合 · BGE-Reranker-v2-M3 · Evidence                                  │
│  ingestion/   loader · pdf_parser · chunker（文档分段模型）· indexer                                   │
│  providers/   金融数据 Provider Registry（efinance/AKShare/Tencent/Sina/pytdx/BaoStock/                │
│               yfinance + 需 token 的 Tushare）· 优先级路由 · 故障转移 · 熔断                            │
│  mcp/         search · knowledge · financial MCP 服务                                                  │
│  persistence/ MySQL 仓储 + Redis                                                                       │
├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  storage      MySQL 8 (finsage) · Redis · Milvus（+ etcd + MinIO）· 模型位于 resources/models（只读）   │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 3. 数据流（研究请求）

1. 前端提交研究任务 → `api` 创建任务并经 SSE 推送进度与结果。
2. LangGraph 工作流编排各阶段；**确定性引擎**完成全部财务算术；**检索**提供带引用的证据。
3. 每个阶段都经过**核验**（V001–V008），结论获得**六因子置信度**评分，**政策门控**拦截越权/敏感输出。
4. 结果流式返回（`answer.*`、`task.*`）；全过程写入**审计**通道。

各工作流的业务流程细节——节点序列、路由条件与 API 全貌——见[`workflows.zh-CN.md`](workflows.zh-CN.md)。

## 4. 请求/响应与错误契约

- OpenAPI 即契约；Pydantic 模型定义请求/响应；前端使用生成的 TS 客户端（组件中不出现裸 `fetch`）。
- 错误遵循稳定的 `FIN-XXXX` 编码方案，映射为面向用户的消息。
- SSE 使用冻结的事件集（`financial_data.*`、`agent.started|completed`、`answer.*`、`task.*`、`error`），支持 `last-event-id` / 去重。

## 5. 模型资源策略

`resources/models/` 中的本地预下载模型为**只读**；加载时优先使用本地模型，缺失或损坏时回退为在线下载到可配置缓存目录（`FIN_MODEL_CACHE_DIR`）。

## 6. 决策记录（ADR）

影响冻结架构的决策以架构决策记录（ADR）形式沉淀；每条记录包含背景、决策与后果，历史决策及其状态由内部 ADR 索引追踪。
