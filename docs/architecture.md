# FinSage Architecture

This document summarizes the FinSage architecture. The full-stack engineering spec and the
ADR records (design decisions and their status) are internal working documents and are not
published with this repository.

## 1. Principles

- **Deterministic over autonomous.** Deterministic functions/workflows are preferred over
  autonomous agents. Financial arithmetic is always computed by code, never by the LLM.
- **Evidence & audit by construction.** Every claim traces to evidence (with
  `document_id` / `chunk_id` / source) and every node writes an auditable record.
- **Frozen stack.** Milvus, MySQL, Redis, LangGraph, MCP, BGE-M3 and BGE-Reranker-v2-M3 are
  architectural commitments and cannot be replaced without an ADR + explicit approval.
- **Honest degradation.** When an external dependency is not configured (Milvus, MySQL,
  token-gated providers), the related capability is disabled — the system never fabricates
  data or metrics to fill the gap.

## 2. Layers

```text
┌──────────────────────────── apps/web  Next.js + TS + Tailwind + shadcn/ui ────────────────────────────┐
│  Route shell  · ResearchComposer · Answer/Evidence/Calculation/CitationMarker/Trace · SSE client      │
│  (standalone container finsage-web, port 3200 in containerized deployment)                            │
└───────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                            │ REST + SSE                       src/finsage/api  FastAPI
┌───────────────────────────────────────────┴───────────────────────────────────────────────────────────┐
│  api/         auth · routes · SSE · error contract (FIN-XXXX) · task manager                          │
│  agents/      LangGraph workflows (4 graphs: research_qa / financial_health / due_diligence / report) │
│  workflows/   shared research state · checkpoint persistence                                           │
│  governance/  policy · verification (V001–V008) · confidence (6-factor) · audit                        │
│  financial/   deterministic financial engine (growth, ratios, valuation, unit conversion)              │
│  evaluation/  FinEval dataset · evaluators · BenchmarkRunner                                           │
│  retrieval/   BGE-M3 dense/sparse · fusion · BGE-Reranker-v2-M3 · Evidence                             │
│  ingestion/   loader · pdf_parser · chunker (document-segmentation model) · indexer                    │
│  providers/   financial data provider Registry (efinance/AKShare/Tencent/Sina/pytdx/BaoStock/          │
│               yfinance + token-gated Tushare) · priority routing · failover · circuit breaker          │
│  mcp/         search · knowledge · financial MCP servers                                               │
│  persistence/ MySQL repositories + Redis                                                               │
├───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  storage      MySQL 8 (finsage) · Redis · Milvus (+ etcd + MinIO) · models in resources/models (RO)    │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Data flow (research request)

1. Frontend submits a research task → `api` creates a task and streams progress/answers over SSE.
2. Workflow (LangGraph) orchestrates stages; the **deterministic engine** performs all financial
   arithmetic; **retrieval** supplies evidence with citations.
3. Each stage is **verified** (`V001–V008`), claims gain a **six-factor confidence score**, and a
   **policy gate** blocks out-of-scope/sensitive output.
4. Results stream back (`answer.*`, `task.*`); everything is written to the **audit** channel.

Business-process detail for each workflow — node sequences, routing conditions, and API
surface — is documented in [`workflows.md`](workflows.md).

## 4. Request/response & error contract

- OpenAPI is the contract; Pydantic models define request/response; a generated TS client is used
  by the frontend (no bare `fetch` in components).
- Errors follow a stable `FIN-XXXX` code scheme mapped to user-facing messages.
- SSE uses a frozen event set (`financial_data.*`, `agent.started|completed`, `answer.*`, `task.*`,
  `error`) with `last-event-id` / deduplication support.

## 5. Model resources strategy

Local pre-downloaded models in `resources/models/` are **read-only**; loading prefers them and, if
missing or corrupt, falls back to an online download into a configurable cache directory
(`FIN_MODEL_CACHE_DIR`).

## 6. Decision records (ADR)

Decisions that affect the frozen architecture are recorded as architecture decision records
(ADRs); each record captures context, decision, and consequences, and past decisions are
tracked with status in the internal ADR index.
