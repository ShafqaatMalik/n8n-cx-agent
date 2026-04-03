# VoltShop CX Agent

> Production-grade, multi-channel AI customer support automation — built with n8n, Qdrant, Google Gemini, Supabase, Slack, Shopify, and Stripe.

![Architecture](docs/voltshop_architecture.svg)

---

## What it does

VoltShop CX Agent is a fully automated customer support system for an online electronics retailer. It handles the entire support lifecycle — from initial message to resolution — across web chat and email channels.

- **RAG-powered responses** — semantic search over a structured knowledge base, grounded answers returned instantly
- **Transactional automation** — order lookups via Shopify API, refund processing via Stripe API, no human needed
- **Intelligent escalation** — ungrounded or complex queries escalated to Slack with one-click resolution buttons
- **Self-healing KB** — human agent answers fed back into Qdrant via WF5, preventing repeat escalations
- **Structured observability** — every ticket logged to Supabase with 14 fields: intent, grounding, latency, resolution
- **Live analytics dashboard** — real-time visibility into auto-resolve rate, latency percentiles, escalation breakdown, and KB failure points

---

## Tech stack

| Layer | Technology |
|---|---|
| Workflow orchestration | n8n (self-hosted) |
| AI / LLM | Google Gemini via LangChain |
| Vector database | Qdrant |
| Structured logging | Supabase (PostgreSQL) |
| Human escalation | Slack Block Kit |
| Email channel | Gmail OAuth2 |
| Order management | Shopify API |
| Payment processing | Stripe API |
| Frontend | Vanilla HTML/CSS/JS |
| Infrastructure | Docker · GCP Cloud Run |

---

## System architecture

The system consists of 6 n8n workflows:

| Workflow | Role |
|---|---|
| WF2 — Triage | Webhook entry point · normalize input · Gemini intent classification · route |
| WF3 — Action Layer | Shopify order lookup · Stripe refund · 4 routes |
| WF4 — RAG Resolution | Qdrant semantic search · Gemini answer generation · grounding detection |
| WF5 — Feedback Loop | Slack button handler · Gemini FAQ synthesis · Qdrant upsert |
| WF6 — Gmail Intake | Gmail polling · normalize · call WF4 · send reply |
| WF7 — Supabase Logger | Sole DB writer · INSERT new tickets · UPDATE resolved |

### Key design decisions

- WF2 handles both Webhook (frontend) and chat trigger entries via a Normalize Input node — single classification layer regardless of channel
- WF6 bypasses WF2 and calls WF4 directly — email is always RAG-first
- WF3 fires only for explicit transactional intents with order identifiers — classifier prompt enforces this
- WF7 is the only Supabase writer — all workflows route logging through it
- All 3 WF2 exit paths have dedicated Respond to Webhook nodes so the frontend always gets a response
- On Error: Continue on all logging nodes — logging failures never block customer-facing responses

---

## Supabase schema

```sql
CREATE TABLE support_logs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      timestamptz DEFAULT now(),
  channel         text,           -- 'chat' | 'email'
  customer_id     text,           -- sessionId (chat) | sender email (Gmail)
  message         text,
  intent          text,
  confidence      float,
  rag_answer      text,
  grounded        boolean,        -- primary routing signal
  escalated       boolean,
  resolved        boolean DEFAULT false,
  resolution_note text,
  response_ms     int,
  ticket_id       text            -- links Slack buttons to Supabase rows
);
```

---

## WF3 — Refund routes

| Route | Condition | Outcome |
|---|---|---|
| Refund Success | Stripe charge found, amount ≤ threshold | Refund processed instantly |
| Refund Pending | Stripe charge found, amount > threshold | Slack approval request sent |
| No Match | Shopify order exists, no Stripe charge found | Escalation message |
| Order Not Found | Shopify order does not exist | Not-found message |

---

## Test coverage

15 test cases passing across chat, email, and frontend channels — confident path, escalation, mark resolved, resolve + add to KB, all 4 WF3 refund routes, and frontend widget integration.

---

## Key engineering challenges solved

- **Cross-workflow item pairing** — `.item.json` breaks across n8n workflow boundaries; replaced with `.first().json` throughout WF4
- **Stripe pagination** — default limit=5 missed older charges; fixed with limit=100 + customer filter
- **Null detection in n8n If nodes** — `is empty` operator doesn't catch `null`; switched to `does not exist`
- **RAG field mismatch** — n8n LangChain hardcodes `content` field; original KB used `text`; resolved by re-ingesting entire KB
- **Classifier over-routing** — delivery address and policy questions incorrectly routed to WF3; fixed via explicit prompt rules
- **Webhook entry point** — n8n chat trigger can't receive external POSTs; added Webhook node + Normalize Input Code node to unify both entry points under a single classification layer
- **WF7 insert vs update routing** — missing `action` field in WF5 payload caused WF7 to always INSERT instead of UPDATE; fixed by explicitly including `action: "update"` in the Mark Resolved HTTP POST

---

## Known limitations

- No session memory — each message is a stateless execution; multi-turn conversations require the customer to provide all context in a single message (designed fix: `pending_sessions` Supabase table + WF2 pre-check)
- Gmail uses snippet (~100 chars) rather than full MIME body — sufficient for short queries
- WF7 webhook endpoint is unauthenticated — relies on network-level security (localhost / VPC)
- No response caching for repeated identical queries

---

## Prerequisites

- n8n self-hosted (Docker)
- Qdrant (Docker)
- Supabase project (cloud)
- Google Cloud project with Gemini API + Gmail OAuth2 enabled
- Slack app with Block Kit + Interactive Components
- Shopify Partner sandbox store
- Stripe sandbox account

---

## Local infrastructure

```bash
docker-compose up -d   # starts n8n + Qdrant
```

Import workflow JSONs from `/workflows` into n8n, configure credentials, run the ingestion script:

```bash
python scripts/ingest_knowledge_base.py
```

---

## Project structure

```
n8n-cx-agent/
├── index.html                        # VoltShop storefront + VoltBot chat widget
├── voltshop_architecture.svg         # System architecture diagram
├── voltshop_architecture.md          # Mermaid architecture diagram (GitHub-renderable)
├── docker-compose.yml                # n8n + Qdrant local setup
├── .env.example                      # Environment variable reference
├── requirements.txt                  # Python dependencies (Python 3.14)
├── dashboard/
│   └── voltshop_dashboard.html       # Live analytics dashboard (Supabase-connected)
├── workflows/
│   ├── WF2 — Triage.json
│   ├── WF3 — Action Layer.json
│   ├── WF4 — RAG Resolution.json
│   ├── WF5 — Feedback Loop.json
│   ├── WF6 — Gmail Intake.json
│   └── WF7 — Supabase Logger.json
├── knowledge-base/
│   ├── return-policy.md
│   ├── shipping-policy.md
│   ├── technical-support-faq.md
│   ├── product-catalog-faq.md
│   ├── account-billing-faq.md
│   └── warranty-policy.md
└── scripts/
    └── ingest_knowledge_base.py
```


