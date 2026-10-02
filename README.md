# VoltShop CX Agent

[![CI — Validate Workflows](https://github.com/ShafqaatMalik/n8n-cx-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ShafqaatMalik/n8n-cx-agent/actions/workflows/ci.yml)
[![CD — Deploy to Cloud Run](https://github.com/ShafqaatMalik/n8n-cx-agent/actions/workflows/cd.yml/badge.svg)](https://github.com/ShafqaatMalik/n8n-cx-agent/actions/workflows/cd.yml)

A production-grade AI customer support automation system. Multi-channel intake (chat webhook, Gmail), agentic RAG over a self-healing Qdrant knowledge base, transactional action handling against live Shopify and Stripe sandboxes, human-in-the-loop escalation via Slack, and real-time observability through a Supabase-backed analytics dashboard — running on Google Cloud Run (scale to zero, free tier) with full CI/CD.

**[Live Demo](https://verdant-kringle-543ae3.netlify.app)** · **[Analytics Dashboard](https://verdant-kringle-543ae3.netlify.app/voltshop_dashboard.html)** · **[Demo Video](https://github.com/ShafqaatMalik/n8n-cx-agent/releases/download/v1.0/VoltShop_Demo_Final.mp4)**

Demo system on scale-to-zero hosting: the first message after idle takes ~20 s while the agent wakes up.

---

## Key results

Measured in April 2026 on the previous always-on host — details in [docs/performance.md](docs/performance.md).

| Metric | Result |
|---|---|
| Auto-resolve rate (live dashboard, 3,500+ tickets) | 84% |
| Cache hit rate (grounded load test, 989 tickets) | 95.6% |
| HTTP success and throughput (both load tests) | 100% at 5.9 req/s |
| p95 latency | 4.7 s grounded · 7.2 s mixed |

---

## Architecture

VoltShop CX Agent handles the full customer support lifecycle. It manages policy queries via RAG, processes order and refund actions against live Shopify/Stripe sandboxes, escalates unresolvable tickets to Slack with human-in-the-loop resolution buttons, and ingests support emails via Gmail. Every ticket is logged to Supabase with structured metadata and surfaced in a real-time observability dashboard.

The architecture is intentionally modular: each workflow owns a single responsibility and communicates via n8n's sub-workflow execution protocol. This makes individual components independently testable and replaceable without touching the rest of the pipeline.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         WF2 — Triage                                 │
│                                                                      │
│  Webhook ──┐                                                         │
│            ├──► Normalize Input ──► djb2 Hash ──► Cache Lookup       │
│  Chat  ────┘                                     │                   │
│                                           hit ◄──┘──► miss           │
│                                            │              │          │
│                                 Respond (~0.7–1.2 s)  Gemini         │
│                                 Log cache hit         Classify       │
│                                                            │         │
│                              ┌─────────────┬──────────────┤          │
│                           escalate      action           RAG         │
└──────────────────────────────┼─────────────┼──────────────┼──────────┘
                               │             │              │
                               │             │              │
                    ┌──────────▼──┐  ┌───────▼───────┐  ┌───▼──────────────┐
                    │Slack alert  │  │  WF3          │  │ WF4              │
                    │Supabase log │  │  Action Layer │  │ RAG Resolution   │
                    │Respond      │  │               │  │                  │
                    └─────────────┘  │ Gemini NER    │  │ Qdrant retrieval │
                                     │ Shopify API   │  │ Confidence parse │
                                     │ Stripe API    │  │ Cache write      │
                                     │               │  │ Grounded → log   │
                                     │ 4 exit paths: │  │ Ungrounded →     │
                                     │ refund_success│  │ Slack + log      │
                                     │ refund_pending│  └──────────────────┘
                                     │ no_match      │
                                     │ order_not_fnd │
                                     └───────────────┘

  Gmail ──► WF6 (poll, 1 min, while awake) ──► filter self-replies ──► WF4 ──► reply

  Slack button ──► WF5 ──► mark_resolved  → WF7: resolved=true
                       └──► resolve_add_kb → agent's Slack thread reply → Gemini FAQ entry
                                             → embed + insert into Qdrant → WF7: resolved + resolution_note

  All paths ──► WF7 (log-ticket webhook) ──► Supabase support_logs
                 retry: 3 attempts, 1s wait
```

![VoltShop CX Agent — System Architecture](docs/voltshop_architecture.svg)

---

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| [WF2 — Triage](docs/WF2_Triage.md) | Chat webhook | Normalises input, checks the cache, classifies with Gemini and routes to escalation, WF3 or WF4 |
| [WF3 — Action Layer](docs/WF3_Action_Layer.md) | Called by WF2 | Order lookups and refunds against Shopify and Stripe, with four exit paths |
| [WF4 — RAG Resolution](docs/WF4_RAG_Resolution.md) | Called by WF2 and WF6 | RAG over Qdrant with a grounding check; confident answers are cached, the rest escalate to Slack |
| [WF5 — Feedback Loop](docs/WF5_Feedback_Loop.md) | Slack button | Marks tickets resolved, or turns the agent's thread reply into a new knowledge-base entry |
| [WF6 — Gmail Intake](docs/WF6_Gmail_Intake.md) | Gmail poll (while awake) | Answers labelled support emails through WF4 |
| [WF7 — Supabase Logger](docs/WF7_Supabase_Logger.md) | Log webhook | Writes every ticket to Supabase `support_logs` |

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| Workflow orchestration | n8n 2.17.7 (official image, pinned) | Visual debuggability, native sub-workflow protocol, credential isolation per node. |
| Hosting | Google Cloud Run — Tokyo (`asia-northeast1`) | Scales to zero, so an idle demo costs nothing; one pinned container; HTTPS and WebSockets built in. An earlier attempt was rejected because the n8n editor stayed "offline" — see [Why Cloud Run works now](docs/deployment.md#why-cloud-run-works-now). |
| n8n's own database | Supabase Postgres (Tokyo), separate `n8n` schema, via the session pooler | Cloud Run containers are stateless, so n8n's workflows, credentials and executions must live in an external database. Reusing the existing Supabase project avoids paying for Cloud SQL. |
| LLM | Google Gemini `gemini-flash-lite-latest`, temperature 0 (free-tier API key) | Low latency, strong instruction following, free tier. The choice was limited by what the free-tier key accepts — see [Known Limitations](docs/operations.md#known-limitations) for what each model returned. |
| Vector store | Qdrant Cloud free tier (Frankfurt, GCP) | Cosine similarity, payload filtering, free managed tier with 3072-dim support. |
| Embeddings | Gemini Embedding 001 (3072 dims) | 3072 dimensions, same provider as LLM, no additional credential. |
| Ticket store | Supabase (Postgres) — `support_logs`, `response_cache` | Structured logging, RLS, REST API without ORM overhead. Native Postgres means no migration risk if moving off Supabase. |
| Cache hash | djb2 | O(n) string hash, no crypto module dependency in n8n Code node, deterministic collision resistance sufficient for query-length strings. |
| Cache operations | Native Supabase node | HTTP Request node for Supabase PATCH/INSERT silently fails without error output in n8n — native Supabase node handles auth and operations correctly with visible output. |
| Messaging | Slack (interactive buttons) | Where support agents already work; Block Kit buttons give one-click resolution and feed the self-healing KB. |
| Email | Gmail (OAuth2, poll trigger) | A second real channel with no extra infrastructure; the poll trigger needs no public inbound webhook. |
| Commerce | Shopify Admin API, Stripe API (sandboxes) | Real APIs in sandbox mode, so lookups and refunds are genuine transactions without real money. |
| Frontend | Vanilla HTML/CSS/JS — Netlify, deployed from GitHub | No build pipeline, no framework dependency; Netlify serves the `dashboard/` folder straight from GitHub. |
| Secrets | n8n credential store (service keys), Google Secret Manager (deploy secrets), GitHub Secrets (CI/CD) | No token in any workflow file or the repo; each secret lives only where it is used. |
| CI/CD | GitHub Actions — CI, CD to Cloud Run (Workload Identity Federation), keep-alive | n8n's native Git integration requires an Enterprise licence. Pushing workflows through n8n's public REST API from Actions is portable and plugin-free. |

---

## Engineering highlights

- **Self-healing knowledge base** — one Slack click turns a human agent's reply into a new Qdrant entry (WF5), so the same question is answered automatically next time.
- **Grounding gate** — every RAG answer carries a confidence score and a grounded flag; ungrounded answers go to Slack with resolution buttons instead of being sent as fact.
- **Cache in front of the LLM** — repeat questions skip Gemini and answer in ~0.7–1.2 s (95.6% hit rate in the grounded load test).
- **Real transactions with guardrails** — refunds up to $50 are processed automatically in Stripe; larger ones wait for approval in Slack.
- **$0 hosting that scales to zero** — n8n on Cloud Run (max 1 instance) with its state in Supabase Postgres; a cold start takes ~15–20 s.
- **Safe CI/CD** — CD deploys only changed workflows, keeps live credentials and Gmail poller state, and logs in through Workload Identity Federation (no key file); a CI guard blocks secrets and unsafe Cloud Run settings.

---

## Known limitations (top 5)

- **Cold start:** the first request after ~15 minutes idle takes ~15–20 s.
- **Gmail only while awake:** emails that arrive while the service sleeps are answered at the next wake-up.
- **$1 spending cap:** if it is reached, the whole system pauses until the cap is raised or the month resets.
- **Unauthenticated webhooks:** WF5 (Slack buttons) does not verify Slack's signature and WF7 (logging) accepts any POST.
- **Free-tier Gemini:** per-minute limits with no retry on 429, and a `-latest` model alias Google can repoint.

Full list, with causes and fixes: [docs/operations.md](docs/operations.md#known-limitations).

---

## Demo warm-up

1. `curl https://n8n-389802584130.asia-northeast1.run.app/health`, then wait ~20 s.
2. Run the demo; Slack buttons only work while the instance is warm.
3. Never leave a `run.app` browser tab open — it keeps the service awake and billed ([details](docs/operations.md#demo-warm-up)).

---

## Documentation

| Document | Contents |
|---|---|
| [docs/deployment.md](docs/deployment.md) | Production deployment, why Cloud Run works now, CI/CD |
| [docs/operations.md](docs/operations.md) | Failure modes, all known limitations, demo warm-up, spending cap, keep-alive, backups |
| [docs/performance.md](docs/performance.md) | Load tests, live dashboard numbers, observability (incl. the p95 caveat) |
| [docs/data-model.md](docs/data-model.md) | `support_logs` and `response_cache` schemas, RLS |
| [docs/local-setup.md](docs/local-setup.md) | Local setup, repository structure |
| [docs/voltshop_architecture.md](docs/voltshop_architecture.md) | Architecture overview |
| [WF2](docs/WF2_Triage.md) · [WF3](docs/WF3_Action_Layer.md) · [WF4](docs/WF4_RAG_Resolution.md) · [WF5](docs/WF5_Feedback_Loop.md) · [WF6](docs/WF6_Gmail_Intake.md) · [WF7](docs/WF7_Supabase_Logger.md) | One document per workflow: diagram, nodes, design decisions |

---

## Author

**Shafqaat Malik**
[LinkedIn](https://linkedin.com/in/shafqaatmalik)
