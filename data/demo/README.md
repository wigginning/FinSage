# FinSage Demo Dataset

`data/demo/` ships seed documents for the three frontend E2E demos. These are **synthetic, demo-only**
materials — they are **not** real financial filings and must never be presented as real market data.

> Security note: external documents are untrusted input. These files are only for local ingestion
> demos and are intentionally small and benign.

## Use cases (1 file each)

| File | E2E demo | What it exercises |
|---|---|---|
| `600519-maotai-2024.md` | 营收净利润变化 | retrieval + numeric engine (revenue/net-profit growth); company detail |
| `financial-anomaly-2024.md` | 财报异常 | anomaly detection → verification / abstention (negative margin, zero/negative denominators) |
| `due-diligence-acme.md` | 模拟尽调 | due-diligence workflow over a fixed dossier |

## How to ingest

Each file is plain Markdown (a supported document type). In the Documents UI, upload a file and
wait for processing (`queued → running → completed`), then open its detail view. After ingestion you
can submit a research query that targets the document.

## Contents

The numbers inside the demo files are fabricated to be internally consistent so the deterministic
engine yields a stable, repeatable answer (e.g. year-over-year growth matching the printed figures).
They exist to make the demo deterministic — not to reflect any real company's financials.