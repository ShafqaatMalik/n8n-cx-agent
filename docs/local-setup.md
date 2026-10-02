# Local setup

[← README](../README.md)

---

## Local Setup

```bash
git clone https://github.com/ShafqaatMalik/n8n-cx-agent
cd n8n-cx-agent
cp .env.example .env
# Edit .env — the scripts read GEMINI_API_KEY, QDRANT_HOST, QDRANT_API_KEY, QDRANT_COLLECTION

python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d  # starts n8n on localhost:5678 (local SQLite) and a local Qdrant on :6333
```

**Which Qdrant?** `.env.example` points the scripts at the docker-compose Qdrant (`QDRANT_HOST=http://localhost:6333`, no API key). The production knowledge base lives in Qdrant Cloud; set `QDRANT_HOST` (cluster URL with `:6333`) and `QDRANT_API_KEY` to it only when you intend to change production. The local n8n's Qdrant credential must point at the same Qdrant as the scripts.

> **Warning:** `scripts/ingest_knowledge_base.py` **deletes and recreates** the collection with new point IDs. Run against Qdrant Cloud, it wipes every point added through WF5's "Resolve + Add to KB". Back up first: `python3 scripts/backup_qdrant.py` (JSONL + snapshot in `~/voltshop-backups/`).

**Credential setup order matters:**

1. Create Qdrant, Supabase, Gemini, Slack, Gmail, Shopify, Stripe credentials in n8n first
2. Import workflow JSONs from `workflows/`
3. Re-link credentials in each workflow (IDs differ between instances)
4. Run KB ingest before activating WF4

```bash
python scripts/ingest_knowledge_base.py
```

**WF7 must be activated before any other workflow** — it is the logging dependency for WF2, WF3, WF4 and WF5.

---

## Repository Structure

```
n8n-cx-agent/
├── workflows/                       # n8n workflow JSONs (WF2–WF7)
│   ├── WF2_Triage.json
│   ├── WF3_Action_Layer.json
│   ├── WF4_RAG_Resolution.json
│   ├── WF5_Feedback_Loop.json
│   ├── WF6_Gmail_Intake.json
│   └── WF7_Supabase_Logger.json
├── knowledge-base/                  # FAQ markdown files → Qdrant chunks
│   ├── account-billing-faq.md
│   ├── product-catalog-faq.md
│   ├── return-policy.md
│   ├── shipping-policy.md
│   ├── technical-support-faq.md
│   └── warranty-policy.md
├── scripts/
│   ├── ingest_knowledge_base.py     # Rebuild the KB collection (deletes and recreates — see Local Setup)
│   ├── load_test_grounded.py        # 989-ticket grounded RAG load test
│   ├── load_test_mixed.py           # 500-ticket mixed realistic load test
│   ├── deploy_workflows.py          # CD: push changed workflows to the Cloud Run n8n
│   ├── ci_guard.py                  # CI: block secrets, old hosts, unsafe Cloud Run config
│   └── backup_qdrant.py             # One-off KB backup (JSONL + snapshot, saved outside the repo)
├── dashboard/                       # Published by Netlify (see netlify.toml)
│   ├── index.html                   # VoltShop storefront + VoltBot chat widget
│   └── voltshop_dashboard.html      # Real-time analytics dashboard
├── infra/cloudrun/service.yaml      # Cloud Run service definition (no secret values)
├── docs/
│   ├── deployment.md · operations.md · performance.md · data-model.md · local-setup.md
│   ├── voltshop_architecture.md
│   ├── voltshop_architecture.svg
│   └── WF2_Triage.md – WF7_Supabase_Logger.md
├── load_test_grounded_results.json  # 989-ticket grounded load test results
├── load_test_mixed_results.json     # 500-ticket mixed load test results
├── docker-compose.yml               # Local n8n development setup
├── .env.example                     # Variables for the Python scripts and docker-compose (copy to .env)
├── netlify.toml                     # Static site: publish dashboard/, no build
├── requirements.txt
├── .flake8
└── .github/workflows/
    ├── ci.yml                       # JSON, required files, flake8, guard
    ├── cd.yml                       # Deploy to Cloud Run (service + changed workflows)
    └── keepalive.yml                # Mon/Thu read-only pings to Supabase and Qdrant
```
