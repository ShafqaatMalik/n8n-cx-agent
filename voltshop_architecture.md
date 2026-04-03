## VoltShop CX Agent — System Architecture

```mermaid
flowchart TD
    WC([Web Chat Widget]) --> WF2
    GM([Gmail Inbox]) --> WF6

    WF2["**WF2 — Triage**\nWebhook entry point · Normalize Input\nGemini classify · route by intent"]
    WF6["**WF6 — Gmail Intake**\nGmail API · normalize · filter sender · call WF4"]

    WF6 -->|RAG| WF4
    WF2 -->|action intent + order or refund| WF3
    WF2 -->|RAG intent| WF4
    WF2 -->|direct escalation| SL[(Slack)]

    WF3["**WF3 — Action Layer**\nShopify order lookup · Stripe refund\n4 routes: success · pending · no-match · not-found"]
    WF4["**WF4 — RAG Resolution**\nQdrant KB · Gemini generate\ngrounded=true → auto-resolve\ngrounded=false → escalate"]

    WF3 -->|refund pending approval| SL
    WF3 -->|no-match alert| SL
    WF3 -->|order-not-found alert| SL
    WF4 -->|escalation| SL

    SL -->|Mark Resolved · Resolve + Add to KB · via ngrok| WF5

    WF5["**WF5 — Feedback Loop**\nSlack button handler\nGemini FAQ gen · Qdrant upsert\nupdates Supabase via WF7"]

    WF2 -->|log| WF7
    WF3 -->|log| WF7
    WF4 -->|log| WF7
    WF5 -->|mark resolved| WF7

    WF7["**WF7 — Supabase Logger**\nsole writer to support_logs\nroutes: insert new · update resolved"]

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
```

### Channel flow summary

| Entry point | How it enters | Triage | Resolution |
|---|---|---|---|
| Web chat widget | POST to WF2 Webhook → Normalize Input | WF2 | WF3 (action) or WF4 (RAG) |
| Gmail inbox | WF6 polls Gmail → normalizes → calls WF4 | — | WF4 direct |

### Workflow responsibilities

| Workflow | Role | Key integrations |
|---|---|---|
| WF2 — Triage | Webhook entry point · normalize input · classify intent · route | Gemini, Slack |
| WF3 — Action Layer | Shopify order lookup · Stripe refund processing · 4 routes | Shopify, Stripe, Slack |
| WF4 — RAG Resolution | KB-grounded answers · escalate if ungrounded | Qdrant, Gemini, Slack |
| WF5 — Feedback Loop | Slack button handler · self-healing KB · ticket resolution | Qdrant, Slack, WF7 |
| WF6 — Gmail Intake | Email channel adapter · normalize · call WF4 · send reply | Gmail API |
| WF7 — Supabase Logger | Sole DB writer · INSERT new tickets · UPDATE resolved | Supabase support_logs |

### Key design decisions

- WF2 is the single web chat entry point — Webhook node receives POST from frontend, Normalize Input node extracts chatInput and sessionId before classification
- WF6 bypasses WF2 and calls WF4 directly — email is always a RAG-first flow
- WF3 only fires for explicit transactional intents — classification prompt enforces this
- WF7 is the only workflow that writes to Supabase — all others route through it
- Slack button callbacks travel: Slack → ngrok → WF5 webhook
- All 3 WF2 exit paths (escalation, action, RAG) have dedicated Respond to Webhook nodes
