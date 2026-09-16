# FinSage Security Model

> 中文版：请见 [`security.zh-CN.md`](security.zh-CN.md)

This document states FinSage's security model and trust boundaries. It codifies §26.16 (Frontend
Security Contract) and the security rules of `AGENTS.md` (§31.7 equivalent) into a single,
operational reference.

## 1. Trust boundaries

```text
[ User Browser ] ──┬─ trusted: HTTP + issued/validated tokens
                   │
[ apps/api ] ──────┴─ trusted origin boundary
        │  trusted: internal typed interfaces (OpenAPI contracts)
        ├── [ models / internal services ]          trusted code + resources (models read-only)
        ├── [ providers (AKShare/BaoStock/yfinance) ] semi-trusted: validate & normalize everything
        └── [ retrieved docs / web content ]        UNTRUSTED input, always
```

- **Trust tokens** must never be embedded in source code, logs, images, or the client bundle.
- **External document/web content is untrusted**: it is parsed as data, never executed, and never
  allowed to override system instructions (prompt-injection defense).

## 2. Frontend security contract (§26.16)

- Token/session values are **never** written into source code.
- **API keys never ship in the client bundle**; they are configured server-side only.
- **Do not trust rendered Markdown/HTML from external content**; sanitize/escape on output.
- **Evidence text renders as plain text by default** to neutralize embedded HTML/script.
- **External links** open with a safe strategy (`rel="noopener noreferrer"`).
- **Never surface raw backend stack traces** to the client; errors map to a stable `FIN-XXXX` code
  with a user-safe message.

## 3. Server & data security (§31.7)

- **Never commit API keys.** Only `.env.example` / `.env.local.example` samples are tracked;
  `.env.*` are git-ignored.
- **Never log secrets.** Input/output telemetry excludes credentials and tokens.
- **Secrets are never stored in the audit store.** `AuditEntry` captures model/tool/provider and
  operational metadata — sensitive values are excluded by construction.
- **Least privilege.** Service accounts are granted only the database/object/permission scopes the
  service needs; default `FIN_DB_USER`/passwords in `docker-compose.yml` are for **local dev only**
  and must be replaced via environment variables in any real deployment.

## 4. Runtime hygiene

- All middleware is async; no callback style (keeps error/cleanup paths deterministic).
- Trace IDs (`X-Trace-Id`) propagate through requests; retrieval preserves `document_id`/`chunk_id`/
  source so every claim is traceable.
- Policy gate blocks out-of-scope and sensitive output; verification prevents unsupported claims
  from being surfaced as high-confidence facts.
- Financial numbers come from the deterministic engine, so the exposure surface on arithmetic is
  code, not model reasoning.

## 5. Reporting

Security-sensitive changes are subject to the same ADR review as architecture changes — a
change to any trust boundary must be an Accepted ADR before implementation.