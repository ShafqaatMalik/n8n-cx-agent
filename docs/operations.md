# Operations

[← README](../README.md)

---

## Failure Modes and Degradation

| Failure | Impact | Behaviour |
|---|---|---|
| Gemini API down | WF2 classification fails | WF2 defaults to RAG route; WF4 RAG agent fails; customer receives error response |
| Gemini 429 (rate limit) | Intermittent LLM failures | Request fails; no retry implemented; 0.7% failure rate observed under load |
| Qdrant unavailable | RAG retrieval fails | WF4 agent returns ungrounded response; escalates to Slack |
| Supabase write failure | Ticket not logged | WF7 retries 3×; ticket processed but not logged — silent data loss |
| Shopify API auth failure | WF3 order lookups fail | Entire WF3 execution fails; customer receives error response |
| Cloud Run scaled to zero | First request waits ~15–20 s | Cold start; VoltBot shows "Waking up the agent…" after 5 s and retries for up to 90 s. Slack button clicks and Gmail are affected — see Known Limitations |
| Cloud Run instance restart (deploy, cold start) | Brief unavailability | Workflows re-register on boot; WF6's Gmail poller state is in the database, so no email is answered twice |
| $1 spending cap reached | Whole system offline | The cap pauses the Cloud Run service; chat, email, Slack buttons and logging stop until the cap is raised or the month resets |
| Supabase or Qdrant paused for inactivity | Startup / RAG failures | Prevented by the keep-alive job; if it fails, GitHub emails the repo owner |
| Cache duplicate key | Cache entry not written | Write Cache is a plain insert; a duplicate `query_hash` fails on the unique constraint, but On Error → Continue keeps the answer and the WF7 log call running. Expired rows are removed nightly by `pg_cron`, so they cannot cause this |
| Slack token expired | Escalation silent failure | Slack nodes return `not_authed`; ticket logged but agent not notified. Fix by updating the `Slack Bot` credential in n8n |

---

## Known Limitations

**Cold start: about 15–20 s after idle**
Cloud Run scales n8n to zero about 15 minutes after the last request. The next request starts a new instance: `/health` answers after ~15 s and webhooks work after ~20 s. VoltBot covers this with a "Waking up the agent…" message and retries; for demos, warm up first (see [Demo warm-up](#demo-warm-up)).

**Gmail is only polled while the service is awake**
WF6 polls every minute, but only while an instance is running. An email that arrives while n8n is asleep is answered on the next wake-up, together with any others that arrived in the meantime. There is no real-time email reply between demos.

**The $1 spending cap can pause everything**
The Cloud Run service has a $1/month spending cap with enforcement. If it is reached, Google pauses the service and every channel stops until the cap is raised or the next month starts. To lift it, go to Google Cloud console → Billing → Budgets & alerts → `n8n-cx-agent-budget`, raise the amount or turn off enforcement, then call `/health` to confirm the service answers. Normal demo use stays far below the cap; the main risk is something keeping the instance awake — such as an open browser tab on the service URL, which once woke it about 30 times in one night.

**Slack button clicks fail on a cold instance**
Slack waits only 3 seconds for an interactivity response and does not retry. A Mark Resolved or Resolve + Add to KB click that wakes the instance fails (Slack shows an error), and has to be clicked again once n8n is warm.

**Free-tier idle limits (covered by the keep-alive job)**
Supabase pauses free projects after about a week without activity; Qdrant Cloud suspends free clusters after 1 week idle and deletes them after 4 weeks. The keep-alive job reads from both every Monday and Thursday. GitHub disables scheduled workflows in public repositories after 60 days without a commit; it emails a warning first, and re-enabling is one click.

**No session memory**
Each message is stateless. Multi-turn conversations require the customer to provide full context in a single message. Designed fix: `pending_sessions` Supabase table + WF2 pre-check.

**Cache hash is exact-match only**
djb2 hashes normalised query strings. Typos produce different hashes and bypass cache. `"what is your return policy?"` and `"what is you return policy?"` are separate cache entries. Fuzzy/semantic cache matching would require embedding comparison.

**Cache staleness**
KB updates via WF5 take effect immediately for new queries but existing cache entries are not invalidated. No active cache invalidation is implemented.

**Gmail snippet only**
WF6 processes Gmail snippet (~100 chars) rather than full MIME body. Sufficient for short queries; may miss context in long emails.

**No WF7 authentication**
WF7's `log-ticket` webhook endpoint has no authentication: anyone who knows the URL can POST a row into `support_logs` or mark a ticket resolved. The Supabase RLS lockdown does not help here, because WF7 writes with the service role. Accepted for a demo system; the fix would be header authentication on the WF7 webhook and on every caller.

**Supabase connection pool exhaustion**
Free tier Postgres has a connection pool ceiling. At sustained concurrency >15, write failures occur silently. WF7 retries 3× but pool exhaustion can cause all retries to fail.

**n8n HTTP Request node silently fails on Supabase PATCH/INSERT**
HTTP Request nodes configured to POST/PATCH Supabase REST API return empty output with no error when the operation fails (RLS violation, malformed body, auth issue). Native Supabase nodes expose errors correctly. All cache operations (Write Cache, Increment Hit Count) use native Supabase nodes as a result.

**Gemini model choice is limited by the free-tier key**
What each chat model returned on this project's free-tier key (September–October 2026):

- `gemini-2.5-flash`: refused for newly created keys.
- `gemini-2.5-flash-lite`: `404 Not Found` (not available to the key).
- `gemini-3.8-flash` (preview): `503 Service Unavailable`.
- `gemini-flash-latest`: `503 Service Unavailable` ("high demand") on 4 of 5 test questions.
- `gemini-flash-lite-latest`: works. At default temperature it intermittently emitted an empty tool call (2 of 12 RAG requests), which WF4 routed to escalation; at temperature 0 it answered 15 of 15 test questions grounded. All chat model nodes use it at temperature 0.

`-latest` is an alias that Google can repoint to a newer model without notice, which may change answer style or tool-calling behaviour. If RAG answers start escalating unexpectedly, check this alias first.

**Free-tier Gemini rate limits**
The Gemini key is on the free tier, which has per-minute and per-day request limits (current values in Google AI Studio). A chat that misses the cache makes at least two Gemini calls (classification, then RAG or entity extraction), so a burst of chats — or a load test — can exceed the per-minute limit. A 429 is not retried: the request fails and the customer gets an error. The 0.7% 429 rate under Failure Modes was measured on the earlier paid key.

**Slack requests to WF5 are not verified**
WF5's webhook does not check Slack's request signature (`X-Slack-Signature`). Anyone who knows the URL could send a forged button payload: mark any ticket resolved, or trigger "Resolve + Add to KB" with a forged customer question and so inject content into the knowledge base. The fix is to verify each request with the Slack app's signing secret (HMAC-SHA256 over the request timestamp and raw body) before WF5 acts.

---

## Demo warm-up

1. Wake the service once (~15–20 s):
   ```bash
   curl https://n8n-389802584130.asia-northeast1.run.app/health
   ```
2. Wait about 20 seconds so webhooks and the Gmail poller are registered, then start the demo.
3. **Never leave a `run.app` browser tab open** — not the editor, not `/health`. Browsers reload such tabs in the background, and every reload keeps the instance awake and billed. Close the editor tab when the demo is over; the service goes back to sleep about 15 minutes after the last request.
4. Slack buttons only work while the instance is warm; if a click fails, click again.

---

## Keep-alive and backups

- **Keep-alive:** `.github/workflows/keepalive.yml` reads one `support_logs` row from Supabase and the `voltshop_kb` collection from Qdrant every Monday and Thursday (06:17 UTC), so neither free tier pauses for inactivity. It never calls n8n or Slack; a failed run emails the repository owner. It can also be started by hand (Actions → Keep-alive → Run workflow).
- **Backups:** `python3 scripts/backup_qdrant.py` exports every Qdrant point (payload and vector) to JSONL and downloads a native snapshot into `~/voltshop-backups/`, outside the repository. Run it before any knowledge-base change and before running `scripts/ingest_knowledge_base.py`.
