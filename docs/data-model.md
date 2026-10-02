# Data Model

[← README](../README.md)

---

## Data Model

### `support_logs` — primary ticket store

```sql
id              uuid        PRIMARY KEY DEFAULT gen_random_uuid()
created_at      timestamptz DEFAULT now()
ticket_id       text        -- epoch ms timestamp, unique per request
channel         text        -- 'chat' | 'email'
customer_id     text        -- sessionId (chat) or sender email (Gmail)
message         text        -- raw customer message
intent          text        -- classified intent from WF2 Gemini agent
confidence      integer     -- 1-5, from WF4 RAG confidence parsing
rag_answer      text        -- final response sent to customer
grounded        boolean     -- true if answer supported by KB retrieval
escalated       boolean     -- true if routed to Slack for human review
resolved        boolean     -- updated by WF5 Slack button callbacks
resolution_note text        -- populated on Resolve + Add to KB
response_ms     integer     -- end-to-end latency from ticket_id timestamp
source          text        -- 'wf2' (cache) | 'wf3' (action) | 'wf4' (RAG)
route           text        -- granular route: cache_hit | refund_success | refund_pending | no_match | order_not_found | confident | escalated
```

### `response_cache` — query-level cache

```sql
id          uuid        PRIMARY KEY
query_hash  text        UNIQUE      -- djb2 hex of normalised query
query_text  text                    -- normalised query for debugging
response    text                    -- cached RAG response
hit_count   integer                 -- incremented on each cache hit
created_at  timestamptz
expires_at  timestamptz             -- TTL: one year from the write; expired rows deleted nightly (pg_cron)
updated_at  timestamptz             -- updated on each cache hit
```

RLS is enabled on both tables. The only policy lets the `anon` role **read** `support_logs` — that is all the public dashboard needs. Anonymous inserts, updates and deletes are rejected, and `response_cache` is not readable without the service role. n8n uses the service role key (stored in its credential store), which bypasses RLS.
