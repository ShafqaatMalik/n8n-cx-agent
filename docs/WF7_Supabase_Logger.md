# WF7 — Supabase Logger

**Role:** Sole database writer. All other workflows route through WF7 to write to Supabase — no other workflow touches the DB directly. Handles two operations: INSERT a new ticket, or UPDATE an existing ticket as resolved. Retry on fail (3 attempts, 1s wait) handles free tier connection pool exhaustion under concurrent load.

---

```mermaid
flowchart TD
    A([Called by WF2 · WF3 · WF4 · WF5\nPOST to /webhook/log-ticket]) --> B[Parse Incoming Payload\nExtract action + all log fields]
    B --> C{action?}

    C -->|insert\nnew ticket| D[Supabase INSERT\nsupport_logs table\nnew row with ticket_id]

    C -->|update\nresolve ticket| E[Supabase UPDATE\nsupport_logs table\nWHERE ticket_id = X\nset resolved=true · resolution_note]

    D --> F([Done])
    E --> F
```

---

## Node summary

| Node | Type | Purpose |
|---|---|---|
| Webhook | Trigger | Receives POST from any upstream workflow at `/webhook/log-ticket` |
| Parse Incoming Payload | Code | Extracts `action` and all field values from request body |
| Route on action | Switch | `action==="insert"` → INSERT · `action==="update"` → UPDATE |
| Supabase INSERT | HTTP Request | Writes new row to `support_logs` — retry on fail: 3 attempts, 1s wait |
| Supabase UPDATE | HTTP Request | PATCHes existing row by `ticket_id` — sets `resolved`, `resolution_note` — retry on fail: 3 attempts, 1s wait |

## support_logs schema

| Column | Type | Set by |
|---|---|---|
| `id` | uuid | Supabase auto |
| `created_at` | timestamptz | Supabase auto |
| `ticket_id` | text | WF2 (generated once, passed to all workflows) |
| `channel` | text | WF2 / WF6 — `'chat'` or `'email'` |
| `customer_id` | text | WF2 sessionId / WF6 From header |
| `message` | text | Raw customer message |
| `intent` | text | WF2 Gemini classifier output |
| `confidence` | integer | WF4 RAG confidence score (1-5) |
| `rag_answer` | text | Final response sent to customer |
| `grounded` | boolean | WF4 grounding flag |
| `escalated` | boolean | WF4 escalation flag |
| `resolved` | boolean | Updated by WF5 via UPDATE route |
| `resolution_note` | text | WF5 agent resolution note |
| `response_ms` | integer | End-to-end latency from `start_time` in Normalize Input |
| `source` | text | `'wf4'` (RAG) or `'wf3'` (action) |
| `route` | text | Granular route: `refund_success`, `order_not_found`, etc. |

## Key design decisions

- **Single writer pattern** — WF7 is the only workflow that writes to Supabase. This prevents race conditions, duplicate rows, and simplifies RLS policy management
- **Routing condition is `action==="update"`** — NOT `resolved===true`. Using `resolved` as the routing condition caused WF5 updates to hit the INSERT route — now fixed
- **Retry on fail enabled** — 3 attempts with 1s wait on both INSERT and UPDATE nodes. Handles transient Supabase free tier connection pool exhaustion under concurrent load without breaking the customer-facing response path
- **`onError: continueRegularOutput`** — logging failures do not propagate back to the caller workflow. The customer-facing response is returned regardless of whether the log write succeeds
- **RLS is enabled** on `support_logs` with a permissive `ALL` policy — anon key used for dashboard reads, service role key used for WF7 writes
