"""
VoltShop CX Agent — Qdrant knowledge-base backup (one-off, read-only on the KB)

Writes, outside the repo by default (~/voltshop-backups/):
  1. <collection>_<timestamp>.jsonl     every point with payload and vector (always)
  2. <collection>_<timestamp>.snapshot  native Qdrant snapshot (when the cluster allows it)

The JSONL export restores into any Qdrant collection with the same vector size
(3072, cosine). The snapshot is removed from the cluster after download so it
does not use the free tier's disk.

Config comes from the repo's .env (never committed) or the environment:
  QDRANT_HOST (or QDRANT_URL)  e.g. https://<cluster>.cloud.qdrant.io:6333
  QDRANT_API_KEY
  QDRANT_COLLECTION            default voltshop_kb

Usage: python scripts/backup_qdrant.py [--out DIR] [--no-snapshot]
Standard library only — no pip install needed.
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE_SIZE = 64


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    url = (os.environ.get("QDRANT_URL") or os.environ.get("QDRANT_HOST") or "").rstrip("/")
    key = os.environ.get("QDRANT_API_KEY", "")
    collection = os.environ.get("QDRANT_COLLECTION") or "voltshop_kb"
    if not url or not key:
        sys.exit("QDRANT_HOST/QDRANT_URL and QDRANT_API_KEY must be set (in .env or the environment)")
    return url, key, collection


def request(method, url, key, body=None, timeout=120):
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"api-key": key, "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def export_jsonl(url, key, collection, path):
    info = json.load(request("GET", f"{url}/collections/{collection}", key))["result"]
    expected = info["points_count"]
    written, offset = 0, None
    with open(path, "w", encoding="utf-8") as out:
        while True:
            body = {"limit": PAGE_SIZE, "with_payload": True, "with_vector": True}
            if offset is not None:
                body["offset"] = offset
            page = json.load(request("POST", f"{url}/collections/{collection}/points/scroll", key, body))["result"]
            for point in page["points"]:
                out.write(json.dumps(point, ensure_ascii=False) + "\n")
                written += 1
            offset = page.get("next_page_offset")
            if offset is None:
                break
    if written != expected:
        sys.exit(f"JSONL export incomplete: wrote {written} of {expected} points")
    return written, info["config"]["params"]["vectors"]


def download_snapshot(url, key, collection, path):
    created = json.load(request("POST", f"{url}/collections/{collection}/snapshots?wait=true", key, timeout=300))
    name = created["result"]["name"]
    try:
        with request("GET", f"{url}/collections/{collection}/snapshots/{name}", key, timeout=300) as resp, \
                open(path, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
    finally:
        request("DELETE", f"{url}/collections/{collection}/snapshots/{name}?wait=true", key).close()
    return name


def main():
    parser = argparse.ArgumentParser(description="Back up the VoltShop Qdrant knowledge base")
    parser.add_argument("--out", default=str(pathlib.Path.home() / "voltshop-backups"),
                        help="output directory (default: ~/voltshop-backups, outside the repo)")
    parser.add_argument("--no-snapshot", action="store_true", help="skip the native snapshot")
    args = parser.parse_args()

    url, key, collection = load_env()
    out_dir = pathlib.Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    jsonl = out_dir / f"{collection}_{stamp}.jsonl"
    count, vectors = export_jsonl(url, key, collection, jsonl)
    print(f"JSONL: {count} points -> {jsonl} ({jsonl.stat().st_size / 1e6:.1f} MB), vectors {vectors}")

    if not args.no_snapshot:
        snapshot = out_dir / f"{collection}_{stamp}.snapshot"
        try:
            name = download_snapshot(url, key, collection, snapshot)
            print(f"Snapshot: {name} -> {snapshot} ({snapshot.stat().st_size / 1e6:.1f} MB), removed from cluster")
        except urllib.error.HTTPError as e:
            snapshot.unlink(missing_ok=True)
            print(f"Snapshot not available ({e.code} {e.reason}); the JSONL export above is the backup")


if __name__ == "__main__":
    main()
