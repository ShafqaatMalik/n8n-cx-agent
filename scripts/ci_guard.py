"""
VoltShop CX Agent — CI guard

Fails the build if anything that must never ship is present:
  - secrets or redaction leftovers in workflows/, infra/ or scripts/
    (tokens belong in the n8n credential store, deploy secrets in Secret Manager)
  - Railway or ngrok URLs (n8n runs on Cloud Run)
  - workflow credential references that are not real 16-character n8n IDs
  - a Cloud Run service definition that could run two Gmail pollers, throttle
    background CPU, or float to an unpinned n8n image

The analytics dashboard's Supabase anon key is public by design and lives outside
the scanned paths.

Usage: python scripts/ci_guard.py [repo_root]    (needs pyyaml)
"""

import json
import pathlib
import re
import sys

import yaml

SCANNED_DIRS = ("workflows", "infra", "scripts")
SELF = pathlib.Path(__file__).name
FORBIDDEN = {
    "redaction leftover": re.compile(r"\bREDACTED\b"),
    "Railway URL": re.compile(r"railway\.app", re.I),
    "ngrok URL": re.compile(r"ngrok", re.I),
    "Slack token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "Stripe key": re.compile(r"[sr]k_(test|live)_[A-Za-z0-9]{10,}"),
    "Shopify token": re.compile(r"shpat_[A-Fa-f0-9]{10,}"),
    "JWT (Supabase/n8n key)": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
}
# (file name, rule) pairs that legitimately mention a pattern: the deploy script refuses REDACTED files
ALLOWED = {("deploy_workflows.py", "redaction leftover")}
CREDENTIAL_ID = re.compile(r"^[A-Za-z0-9]{16}$")
PINNED_N8N_IMAGE = re.compile(r"n8nio/n8n:\d+\.\d+\.\d+$")


def scan_files(root):
    problems = []
    for directory in SCANNED_DIRS:
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or path.name == SELF or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in FORBIDDEN.items():
                if (path.name, label) in ALLOWED:
                    continue
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    problems.append(f"{path.relative_to(root)}:{line}: {label}")
    return problems


def check_credentials(root):
    problems = []
    for path in sorted((root / "workflows").glob("*.json")):
        workflow = json.loads(path.read_text(encoding="utf-8"))
        for node in workflow.get("nodes", []):
            for cred_type, ref in (node.get("credentials") or {}).items():
                if not CREDENTIAL_ID.match(str(ref.get("id", ""))):
                    problems.append(f"{path.relative_to(root)}: node '{node['name']}' {cred_type} "
                                    f"has credential id {ref.get('id')!r}, not an n8n id")
    return problems


def check_service(root):
    path = root / "infra" / "cloudrun" / "service.yaml"
    service = yaml.safe_load(path.read_text(encoding="utf-8"))
    template = service["spec"]["template"]
    annotations = template["metadata"]["annotations"]
    problems = []
    if annotations.get("autoscaling.knative.dev/maxScale") != "1":
        problems.append(f"{path.relative_to(root)}: maxScale must be \"1\" (one Gmail poller)")
    if annotations.get("run.googleapis.com/cpu-throttling") != "false":
        problems.append(f"{path.relative_to(root)}: cpu-throttling must be \"false\" (background work)")
    for container in template["spec"]["containers"]:
        if not PINNED_N8N_IMAGE.search(container["image"]):
            problems.append(f"{path.relative_to(root)}: image {container['image']} is not a pinned n8n version")
    return problems


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = scan_files(root) + check_credentials(root) + check_service(root)
    if problems:
        print(f"CI guard failed ({len(problems)}):")
        for problem in problems:
            print(f"  ✗ {problem}")
        sys.exit(1)
    print("CI guard passed: no secrets, no Railway/ngrok URLs, real credential ids, safe Cloud Run config.")


if __name__ == "__main__":
    main()
