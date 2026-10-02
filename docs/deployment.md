# Deployment

[← README](../README.md)

---

## Production Deployment

```
Browser ──► Netlify (storefront + dashboard, deployed from GitHub main)
   │                 └──► Supabase REST (anon key, read-only on support_logs)
   ▼
Cloud Run "n8n" (Tokyo, 1 instance max, scales to zero)
   ├──► Supabase Postgres, schema n8n  (session pooler, TLS verified with Supabase's CA)
   ├──► Supabase REST (service role, via n8n credential)
   ├──► Qdrant Cloud (Frankfurt) · Gemini API · Shopify · Stripe · Slack · Gmail
   ▲
Slack buttons · Gmail poll (while awake) · VoltBot webhook
```

**Cloud Run service** — defined in `infra/cloudrun/service.yaml` and deployed with `gcloud run services replace` (by CD):

| Setting | Value |
|---|---|
| Image | `docker.io/n8nio/n8n:2.17.7` (pinned; pulled straight from Docker Hub) |
| Region | `asia-northeast1` (Tokyo) — next to the Supabase database, which n8n queries on every execution |
| Scaling | min 0, **max 1** — a second instance would run the Gmail poller twice |
| Billing | instance-based (CPU always allocated while running), 1 vCPU, 2 GiB |
| Timeout / affinity / startup boost | 3600 s / on / on |
| Health endpoint | `/health` (`N8N_ENDPOINT_HEALTH=health`) |
| Execution pruning | keep 7 days, max 5,000 executions — keeps n8n well under Supabase's 500 MB |
| Telemetry | diagnostics and version notifications off |

**n8n's database:** the existing Supabase project, schema `n8n`, role `n8n_app` — it owns the `n8n` schema and has no access to `support_logs` or `response_cache`. It connects through Supabase's **session pooler** on port 5432, which is IPv4 — the direct connection is IPv6-only, and the transaction pooler breaks n8n's migrations. TLS is verified against Supabase's root CA, mounted from Secret Manager (`DB_POSTGRESDB_SSL_CA_FILE`; n8n only reads the CA from a file through the `_FILE` suffix).

**Secrets:** Secret Manager holds the n8n encryption key, the database password, the Supabase CA certificate and the n8n API key; Cloud Run's runtime service account can read only the first three. Service API keys (Gemini, Qdrant, Supabase, Shopify, Stripe, Slack, Gmail) live in n8n's encrypted credential store — no workflow node contains a token.

**Workflows** were imported with their original IDs (`n8n import:workflow`), so sub-workflow calls and CD mappings did not change. Credentials were re-created in the n8n UI.

**Frontend:** Netlify deploys the `dashboard/` folder from GitHub `main` on every push (no build step; `netlify.toml` sets `base = "dashboard"` so Netlify never installs Python dependencies). VoltBot calls the Cloud Run webhook. The analytics dashboard reads `support_logs` directly with the Supabase anon key, which is public by design and limited by RLS to reading that one table.

---

## Why Cloud Run works now

An earlier attempt to run n8n on Cloud Run was abandoned because the n8n editor showed a permanent "offline / connection lost" state. The editor keeps a live push connection (WebSocket) to n8n, and n8n checks that the connection's origin matches the address it believes it is served from. The likely cause: without its public address configured, n8n behind Google's front end compares the browser's `https://…run.app` origin with its own default (plain HTTP, internal host), and rejects the connection. The earlier configuration is not available to confirm this.

What fixed it is telling n8n its real public address and that it sits behind exactly one proxy:

| Setting | Value | Why |
|---|---|---|
| `N8N_HOST`, `N8N_PROTOCOL` | the `run.app` host, `https` | n8n's own idea of its address matches the browser's |
| `N8N_EDITOR_BASE_URL`, `WEBHOOK_URL` | `https://<host>/` | editor links and webhook URLs use the public address |
| `N8N_PROXY_HOPS` | `1` | n8n trusts Google's `X-Forwarded-*` headers for the original protocol and host |
| `N8N_PUSH_BACKEND` | `websocket` | Cloud Run supports WebSockets |
| Request timeout / session affinity | 3600 s / on | long-lived push connections are not cut early |

With these settings the editor stayed connected through a 30-minute test, and executions streamed live into the editor. The setting combination was verified as a whole; it was not narrowed down to one single variable.

Three other Cloud Run issues had to be solved along the way:

- **State:** containers are stateless, so n8n stores everything in Supabase Postgres (own schema), not in a local SQLite file.
- **Background work:** with request-based billing, Cloud Run throttles the CPU between requests. The Gmail poller and work n8n does after answering a webhook (WF5) crawled, and webhooks took ~71 s to come up after a cold start. Instance-based billing keeps the CPU allocated while the instance runs and still scales to zero when idle.
- **Health check path:** Cloud Run reserves some paths ending in `z`; `/healthz` returns 404 from Google's front end and never reaches n8n. n8n's health endpoint is moved to `/health`.

---

## CI/CD

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** (`ci.yml`) | every push and PR to `main` | Python 3.14; validates the workflow JSONs; checks required files; `flake8 scripts/`; runs `scripts/ci_guard.py`, which fails on secrets or redaction leftovers, old hosting URLs, fake credential IDs, or a Cloud Run config with more than one instance, CPU throttling, or an unpinned image |
| **CD** (`cd.yml`) | push to `main` touching `workflows/` or `infra/cloudrun/`; or manual | Redeploys the Cloud Run service only if `infra/cloudrun/` changed, then updates only the workflow files that changed |
| **Keep-alive** (`keepalive.yml`) | Mon + Thu 06:17 UTC; or manual | Reads one Supabase row and the Qdrant collection; never touches n8n or Slack |

**How CD updates a workflow** (`scripts/deploy_workflows.py`): it waits out a cold start, targets the workflow by the `id` in its JSON (it never creates workflows), keeps the live credentials node by node, sends the Gmail poller state back unchanged, skips workflows that already match, re-publishes only workflows that were already active, and never activates or deactivates anything. It then reads the workflow back and fails the run if the active state, credentials or poller state changed. A manual run can check all workflows, redeploy the service, or do a dry run.

**Authentication:** GitHub logs in to Google Cloud through **Workload Identity Federation** — no service-account key exists. Only runs from `main` of this repository are accepted, and the deployer account can update the `n8n` Cloud Run service and nothing else. The n8n API key is a GitHub secret.
