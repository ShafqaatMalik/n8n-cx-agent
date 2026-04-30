## VoltShop CX Agent — System Architecture

```mermaid
flowchart TD
    WC([Web Chat Widget]) --> WF2
    GM([Gmail Inbox]) --> WF6

    WF2["**WF2 — Triage**\nWebhook + Chat Trigger · Normalize Input\ndjb2 hash · cache lookup · Gemini classify · route"]
    WF6["**WF6 — Gmail Intake**\nGmail API · normalize · filter sender · call WF4"]

    WF6 -->|RAG| WF4
    WF2 -->|action intent| WF3
    WF2 -->|RAG intent| WF4
    WF2 -->|direct escalation| SL[(Slack)]
    WF2 -->|cache hit ~800ms| RC[(response_cache)]

    WF3["**WF3 — Action Layer**\nShopify order lookup · Stripe refund\n4 routes: success · pending · no-match · not-found"]
    WF4["**WF4 — RAG Resolution**\nQdrant KB · Gemini generate\ngrounded=true → cache write + auto-resolve\ngrounded=false → escalate"]

    WF3 -->|refund pending| SL
    WF3 -->|no-match alert| SL
    WF3 -->|order-not-found alert| SL
    WF4 -->|escalation| SL
    WF4 -->|grounded response| RC

    SL -->|Mark Resolved · Resolve + Add to KB| WF5

    WF5["**WF5 — Feedback Loop**\nSlack button handler\nQdrant upsert · updates Supabase via WF7"]

    WF2 -->|log| WF7
    WF3 -->|log| WF7
    WF4 -->|log| WF7
    WF5 -->|mark resolved| WF7

    WF7["**WF7 — Supabase Logger**\nsole writer to support_logs\nroutes: insert new · update resolved\nretry: 3 attempts · 1s wait"]

    WF7 --> SB[(Supabase\nsupport_logs)]

    style WF6 fill:#E1F5EE,stroke:#0F6E56,color:#085041
    style WF2 fill:#EEEDFE,stroke:#534AB7,color:#3C3489
    style WF3 fill:#FAECE7,stroke:#993C1D,color:#712B13
    style WF4 fill:#E6F1FB,stroke:#185FA5,color:#0C447C
    style WF5 fill:#FAEEDA,stroke:#854F0B,color:#633806
    style WF7 fill:#FAEEDA,stroke:#854F0B,color:#633806
    style WC fill:#F1EFE8,stroke:#888780,color:#444441
    style GM fill:#F1EFE8,stroke:#888780,color:#444441
    style SL fill:#F1EFE8,stroke:#888780,color:#444441
    style SB fill:#F1EFE8,stroke:#888780,color:#444441
    style RC fill:#F1EFE8,stroke:#888780,color:#444441
```

### Channel flow summary

| Entry point | How it enters | Triage | Resolution |
|---|---|---|---|
| Web chat widget | POST to WF2 Webhook → Normalize Input | WF2 | Cache hit (~800ms) or WF3 (action) or WF4 (RAG) |
| Gmail inbox | WF6 polls Gmail → normalizes → calls WF4 | — | WF4 direct |

### Workflow responsibilities

| Workflow | Role | Key integrations |
|---|---|---|
| WF2 — Triage | Dual trigger · normalize · djb2 hash · cache check · classify · route | Gemini, Supabase (cache), Slack |
| WF3 — Action Layer | Shopify order lookup · Stripe refund processing · 4 routes | Shopify, Stripe, Slack |
| WF4 — RAG Resolution | KB-grounded answers · cache write · escalate if ungrounded | Qdrant, Gemini, Supabase (cache), Slack |
| WF5 — Feedback Loop | Slack button handler · self-healing KB · ticket resolution | Qdrant, Slack, WF7 |
| WF6 — Gmail Intake | Email channel adapter · normalize · call WF4 · send reply | Gmail API |
| WF7 — Supabase Logger | Sole DB writer · INSERT new tickets · UPDATE resolved · retry 3× | Supabase support_logs |

### Key design decisions

- WF2 accepts both Webhook (POST body) and Chat Trigger — Normalize Input produces trigger-agnostic `{chatInput, sessionId, start_time}` before classification
- Cache lookup runs before Gemini classification — cache hits bypass the LLM entirely and respond in ~800ms
- WF6 bypasses WF2 and calls WF4 directly — email is always a RAG-first flow
- WF3 only fires for explicit transactional intents — classification prompt enforces this
- WF7 is the only workflow that writes to Supabase — single writer pattern prevents race conditions
- Slack button callbacks travel: Slack → Railway n8n → WF5 webhook (production — no ngrok)
- All 3 WF2 exit paths (escalation, action, RAG) have dedicated Respond to Webhook nodes
