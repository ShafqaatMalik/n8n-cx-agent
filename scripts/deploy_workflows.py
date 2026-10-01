"""
VoltShop CX Agent — deploy workflow JSONs to the Cloud Run n8n (used by CD)

For each target workflow file:
  - refuses files containing REDACTED; never creates workflows (target = the file's own "id")
  - keeps the live credentials (copied onto file nodes by node name), so CD never overwrites them
  - sends the live staticData back unchanged (WF6's Gmail poller state; resetting it re-answers mail)
  - skips workflows whose nodes, connections and settings already match live
  - PUTs the update, then re-publishes it only if it was already active; never activates or
    deactivates anything
  - reads it back and checks active state, credentials and staticData keys

Targets: workflows/*.json changed since --since <sha> (all of them if the sha is unknown),
or every file with --all. --dry-run prints what would change and writes nothing.
Waits through a Cloud Run cold start (scale-to-zero) before the first API call.

Env: N8N_BASE_URL, N8N_API_KEY. Standard library only.
Usage: python scripts/deploy_workflows.py (--all | --since SHA) [--dry-run]
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / "workflows"
SETTINGS_KEYS = ("executionOrder", "callerPolicy")
NODE_KEYS = ("type", "typeVersion", "parameters", "position", "disabled", "webhookId", "notes", "onError",
             "retryOnFail", "maxTries", "waitBetweenTries", "alwaysOutputData", "executeOnce")
RETRY_STATUSES = {404, 429, 500, 502, 503, 504}


class N8n:
    def __init__(self, base_url, api_key):
        self.base = base_url.rstrip("/")
        self.key = api_key

    def _call(self, method, path, body=None, timeout=60):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-N8N-API-KEY": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw.strip() else {}

    def call(self, method, path, body=None, attempts=4):
        """API call with backoff for transient errors (cold start, 5xx, rate limit)."""
        for attempt in range(1, attempts + 1):
            try:
                return self._call(method, path, body)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                transient = e.code in RETRY_STATUSES and not (e.code == 404 and path.startswith("/api/v1/workflows/"))
                if not transient or attempt == attempts:
                    raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == attempts:
                    raise RuntimeError(f"{method} {path} -> {e}") from None
            time.sleep(5 * attempt)

    def wait_until_ready(self, budget_s=240):
        """Cold start: /health answers first, the API and webhooks some seconds later."""
        deadline, delay = time.time() + budget_s, 5
        for path, label in (("/health", "health"), ("/api/v1/workflows?limit=1", "API")):
            while True:
                try:
                    if path == "/health":
                        with urllib.request.urlopen(self.base + path, timeout=60) as resp:
                            if resp.status == 200:
                                break
                    else:
                        self._call("GET", path)
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                if time.time() > deadline:
                    raise RuntimeError(f"n8n {label} not ready after {budget_s}s")
                print(f"  waiting for n8n {label} (cold start?) ...")
                time.sleep(delay)
                delay = min(delay * 2, 60)
            print(f"  n8n {label} ready")


def changed_files(since):
    all_files = sorted(WORKFLOW_DIR.glob("*.json"))
    if not since or set(since) == {"0"}:
        return all_files
    try:
        out = subprocess.run(["git", "diff", "--name-only", since, "HEAD", "--", "workflows/"], cwd=REPO_ROOT,
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        print(f"  cannot diff against {since}; deploying all workflows")
        return all_files
    names = {line.strip() for line in out.splitlines() if line.strip().endswith(".json")}
    return [f for f in all_files if str(f.relative_to(REPO_ROOT)) in names]


def node_view(node):
    return {k: node[k] for k in NODE_KEYS if k in node}


def merge_live_credentials(file_nodes, live_nodes):
    live_by_name = {n["name"]: n for n in live_nodes}
    merged, warnings = [], []
    for node in file_nodes:
        node = dict(node)
        live = live_by_name.get(node["name"])
        if live and live.get("credentials"):
            node["credentials"] = live["credentials"]
        elif node.get("credentials"):
            warnings.append(f"node '{node['name']}' is new or has no live credentials; using the file's reference")
        merged.append(node)
    return merged, warnings


def differences(desired, live):
    out = []
    want = {n["name"]: node_view(n) for n in desired["nodes"]}
    have = {n["name"]: node_view(n) for n in live["nodes"]}
    out += [f"node added: {name}" for name in sorted(want.keys() - have.keys())]
    out += [f"node removed: {name}" for name in sorted(have.keys() - want.keys())]
    out += [f"node changed: {name}" for name in sorted(want.keys() & have.keys()) if want[name] != have[name]]
    if desired["connections"] != live["connections"]:
        out.append("connections changed")
    live_settings = {k: live.get("settings", {}).get(k) for k in SETTINGS_KEYS if k in desired["settings"]}
    if desired["settings"] != live_settings:
        out.append("settings changed")
    if desired["name"] != live["name"]:
        out.append(f"renamed: {live['name']} -> {desired['name']}")
    return out


def deploy(n8n, path, dry_run):
    text = path.read_text(encoding="utf-8")
    if "REDACTED" in text:
        raise RuntimeError("file contains REDACTED; refusing to deploy")
    wf = json.loads(text)
    live = n8n.call("GET", f"/api/v1/workflows/{wf['id']}")
    nodes, warnings = merge_live_credentials(wf["nodes"], live["nodes"])
    desired = {"name": wf["name"], "nodes": nodes, "connections": wf["connections"],
               "settings": {k: wf["settings"][k] for k in SETTINGS_KEYS if k in wf.get("settings", {})}}
    for w in warnings:
        print(f"    warning: {w}")
    diff = differences(desired, live)
    if not diff:
        return "unchanged"
    for d in diff:
        print(f"    {d}")
    if dry_run:
        return "would update" + (" + re-publish" if live["active"] else "")

    n8n.call("PUT", f"/api/v1/workflows/{wf['id']}", {**desired, "staticData": live.get("staticData")})
    if live["active"]:
        n8n.call("POST", f"/api/v1/workflows/{wf['id']}/activate")

    after = n8n.call("GET", f"/api/v1/workflows/{wf['id']}")
    creds = {n["name"]: n.get("credentials") for n in after["nodes"] if n.get("credentials")}
    expected = {n["name"]: n.get("credentials") for n in nodes if n.get("credentials")}
    checks = {
        "active state unchanged": after["active"] == live["active"],
        "credentials unchanged": creds == expected,
        "staticData keys unchanged": set((after.get("staticData") or {}).keys())
        == set((live.get("staticData") or {}).keys()),
        "no remaining differences": not differences(desired, after),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("post-deploy check failed: " + ", ".join(failed))
    return "updated" + (" + re-published" if live["active"] else " (inactive, not published)")


def main():
    parser = argparse.ArgumentParser(description="Deploy workflow JSONs to the Cloud Run n8n")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="consider every workflow file")
    target.add_argument("--since", help="consider workflow files changed since this git sha")
    parser.add_argument("--dry-run", action="store_true", help="show differences, write nothing")
    args = parser.parse_args()

    base, key = os.environ.get("N8N_BASE_URL"), os.environ.get("N8N_API_KEY")
    if not base or not key:
        sys.exit("N8N_BASE_URL and N8N_API_KEY must be set")
    files = sorted(WORKFLOW_DIR.glob("*.json")) if args.all else changed_files(args.since)
    if not files:
        print("No workflow files changed; nothing to deploy.")
        return

    n8n = N8n(base, key)
    print(f"Target: {base} ({'dry run' if args.dry_run else 'live'}), {len(files)} file(s)")
    n8n.wait_until_ready()
    results, failures = [], 0
    for path in files:
        print(f"  {path.name}")
        try:
            outcome = deploy(n8n, path, args.dry_run)
        except Exception as e:  # report every workflow, then fail the job
            outcome, failures = f"FAILED: {e}", failures + 1
        results.append((path.name, outcome))

    print("\nSummary")
    for name, outcome in results:
        print(f"  {name:34} {outcome}")
    if failures:
        sys.exit(f"{failures} workflow(s) failed")


if __name__ == "__main__":
    main()
