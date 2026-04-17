"""
VoltShop CX Agent — Load Test
Sends 900 async requests to WF2 webhook covering all testable routes.
Usage: python scripts/load_test.py
"""

import httpx
import asyncio
import random
import uuid
import time
import json
from datetime import datetime

WEBHOOK_URL = "https://n8n-production-acb9.up.railway.app/webhook/ce7fb03a-8189-4574-b0fd-8cb1edbd5b09"
TOTAL_TICKETS = 900
CONCURRENCY = 20  # max concurrent requests at once

# Message pool — 20 unique messages, each will fire ~45 times
# Covers: RAG grounded, RAG ungrounded, escalation, order not found, no match
MESSAGES = [
    # RAG — policy questions (will hit cache after first run)
    "What is your return policy?",
    "How long does shipping take?",
    "What is your warranty policy?",
    "Do you offer international shipping?",
    "What payment methods do you accept?",
    "How do I track my order?",
    "What is your cancellation policy?",
    "Do you offer student discounts?",
    "What is the VoltShield warranty?",
    "How do I contact customer support?",

    # RAG — product questions
    "What laptops do you have in stock?",
    "Do you sell refurbished products?",

    # RAG ungrounded — out of scope (will escalate)
    "What is the meaning of life?",
    "Can you recommend a good restaurant near me?",

    # Direct escalation
    "I need to speak to a human agent right now",
    "I want to escalate this to a manager",

    # WF3 — order not found
    "What is the status of my order #88888?",
    "Can you check my order #77777?",

    # WF3 — refund no match
    "I want a refund for my order #55555",
    "Please process a refund for order #66666",
]

results = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "latencies": [],
    "errors": [],
    "start_time": None,
    "end_time": None,
}


async def send_ticket(client: httpx.AsyncClient, message: str, idx: int) -> None:
    payload = {
        "chatInput": message,
        "sessionId": str(uuid.uuid4())
    }
    start = time.time()
    try:
        response = await client.post(
            WEBHOOK_URL,
            json=payload,
            timeout=60.0
        )
        latency = (time.time() - start) * 1000  # ms
        results["latencies"].append(latency)
        results["total"] += 1

        if response.status_code == 200:
            results["success"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({
                "idx": idx,
                "message": message[:50],
                "status": response.status_code,
                "response": response.text[:100]
            })

        if idx % 50 == 0:
            print(f"[{idx}/{TOTAL_TICKETS}] {response.status_code} — {latency:.0f}ms — {message[:40]}")

    except Exception as e:
        latency = (time.time() - start) * 1000
        results["latencies"].append(latency)
        results["total"] += 1
        results["failed"] += 1
        results["errors"].append({
            "idx": idx,
            "message": message[:50],
            "error": str(e)
        })
        if idx % 50 == 0:
            print(f"[{idx}/{TOTAL_TICKETS}] ERROR — {str(e)[:60]}")


async def main():
    print(f"\n{'='*60}")
    print(f"VoltShop CX Agent — Load Test")
    print(f"Target: {WEBHOOK_URL}")
    print(f"Total tickets: {TOTAL_TICKETS}")
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # Build 900 messages — each of 20 messages repeated 45 times
    ticket_messages = []
    for i in range(TOTAL_TICKETS):
        ticket_messages.append(MESSAGES[i % len(MESSAGES)])
    random.shuffle(ticket_messages)

    results["start_time"] = time.time()

    # Send in batches of CONCURRENCY
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def send_with_semaphore(client, message, idx):
        async with semaphore:
            await send_ticket(client, message, idx)

    async with httpx.AsyncClient() as client:
        tasks = [
            send_with_semaphore(client, msg, idx)
            for idx, msg in enumerate(ticket_messages)
        ]
        await asyncio.gather(*tasks)

    results["end_time"] = time.time()
    total_time = results["end_time"] - results["start_time"]

    # Calculate stats
    latencies = sorted(results["latencies"])
    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
    avg = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (results["success"] / results["total"] * 100) if results["total"] > 0 else 0

    print(f"\n{'='*60}")
    print(f"LOAD TEST RESULTS")
    print(f"{'='*60}")
    print(f"Total tickets sent : {results['total']}")
    print(f"Successful         : {results['success']}")
    print(f"Failed             : {results['failed']}")
    print(f"Success rate       : {success_rate:.1f}%")
    print(f"Total time         : {total_time:.1f}s")
    print(f"Throughput         : {results['total']/total_time:.1f} req/s")
    print(f"")
    print(f"Latency (ms):")
    print(f"  Average          : {avg:.0f}ms")
    print(f"  p50              : {p50:.0f}ms")
    print(f"  p95              : {p95:.0f}ms")
    print(f"  p99              : {p99:.0f}ms")
    print(f"  Min              : {min(latencies):.0f}ms")
    print(f"  Max              : {max(latencies):.0f}ms")

    if results["errors"]:
        print(f"\nFirst 5 errors:")
        for err in results["errors"][:5]:
            print(f"  [{err['idx']}] {err.get('error', err.get('status', 'unknown'))}")

    # Save results to file
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_tickets": results["total"],
        "success": results["success"],
        "failed": results["failed"],
        "success_rate": round(success_rate, 1),
        "total_time_seconds": round(total_time, 1),
        "throughput_rps": round(results["total"]/total_time, 1),
        "latency_ms": {
            "avg": round(avg),
            "p50": round(p50),
            "p95": round(p95),
            "p99": round(p99),
            "min": round(min(latencies)),
            "max": round(max(latencies))
        },
        "errors": results["errors"][:10]
    }

    with open("load_test_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to load_test_results.json")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
