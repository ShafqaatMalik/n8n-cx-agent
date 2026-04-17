"""
VoltShop CX Agent — Grounded RAG Load Test
43 questions × 23 repeats = 989 tickets.
Most will hit cache (~800ms). All logged with grounded=true, escalated=false.
Usage: python scripts/load_test_grounded.py
"""

import httpx
import asyncio
import random
import uuid
import time
import json
from datetime import datetime

WEBHOOK_URL = "https://n8n-production-acb9.up.railway.app/webhook/ce7fb03a-8189-4574-b0fd-8cb1edbd5b09"
CONCURRENCY = 10
REPEAT_EACH = 23

MESSAGES = [
    "what is your return policy?",
    "do you offer warranty on your products?",
    "how can i return an item?",
    "how can i apply for a refund?",
    "can i return a used item?",
    "I want to return an item but i lost its accessory",
    "What is your shipping policy?",
    "how to cancel an order?",
    "how can i create an account?",
    "which payments methods are accepted?",
    "I have a billing issue, how to resolve?",
    "do you offer gift cards?",
    "how is tax calculated?",
    "can promotional codes be applied?",
    "what are your product categories?",
    "do you offer price match facility?",
    "how do you make sure product availability?",
    "what are your best selling products?",
    "can you tell me about bulk orders?",
    "do you offer full amount refunds?",
    "what are non-returnable items?",
    "can damaged or defective items be returned?",
    "can you tell me more about late returns?",
    "whats your shipping timeframe?",
    "how soon orders are processed?",
    "how can i track my order?",
    "what are your shipping restrictions?",
    "i have a delivery issue, whom to contact?",
    "i want to change my delivery address, my order has not been shipped yet",
    "i want to change my delivery address, my order has been shipped already",
    "can i refuse or return a package?",
    "tell me more about holiday shipping",
    "my laptop wont turn on, what to do?",
    "monitor has dead pixels, what to do?",
    "whats included in your custom pc?",
    "i have slow performance issues, how to fix?",
    "i have compatibility issues, what to do?",
    "what are your working hours?",
    "do you offer software support?",
    "whats your standard warranty?",
    "whats voltshield?",
    "how to file a warranty claim?",
    "what voids the warranty?",
]

TOTAL_TICKETS = len(MESSAGES) * REPEAT_EACH  # 43 × 23 = 989

results = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "latencies": [],
    "errors": [],
}


async def send_ticket(client: httpx.AsyncClient, message: str, idx: int) -> None:
    payload = {
        "chatInput": message,
        "sessionId": str(uuid.uuid4())
    }
    start = time.time()
    try:
        response = await client.post(WEBHOOK_URL, json=payload, timeout=60.0)
        latency = (time.time() - start) * 1000
        results["latencies"].append(latency)
        results["total"] += 1
        if response.status_code == 200:
            results["success"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"idx": idx, "status": response.status_code})

        if idx % 100 == 0:
            print(f"[{idx}/{TOTAL_TICKETS}] {response.status_code} — {latency:.0f}ms — {message[:45]}")

    except Exception as e:
        latency = (time.time() - start) * 1000
        results["latencies"].append(latency)
        results["total"] += 1
        results["failed"] += 1
        results["errors"].append({"idx": idx, "error": str(e)})


async def main():
    print(f"\n{'='*60}")
    print(f"VoltShop — Grounded RAG Load Test")
    print(f"Unique questions : {len(MESSAGES)}")
    print(f"Repeat each      : {REPEAT_EACH}x")
    print(f"Total tickets    : {TOTAL_TICKETS}")
    print(f"Concurrency      : {CONCURRENCY}")
    print(f"Started          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    ticket_messages = MESSAGES * REPEAT_EACH
    random.shuffle(ticket_messages)

    start_time = time.time()
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

    total_time = time.time() - start_time
    latencies = sorted(results["latencies"])
    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
    avg = sum(latencies) / len(latencies) if latencies else 0
    success_rate = (results["success"] / results["total"] * 100) if results["total"] > 0 else 0

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Total sent       : {results['total']}")
    print(f"Successful       : {results['success']}")
    print(f"Failed           : {results['failed']}")
    print(f"Success rate     : {success_rate:.1f}%")
    print(f"Total time       : {total_time:.1f}s")
    print(f"Throughput       : {results['total']/total_time:.1f} req/s")
    print(f"Avg latency      : {avg:.0f}ms")
    print(f"p50 latency      : {p50:.0f}ms")
    print(f"p95 latency      : {p95:.0f}ms")
    print(f"p99 latency      : {p99:.0f}ms")
    print(f"Min latency      : {min(latencies):.0f}ms")
    print(f"Max latency      : {max(latencies):.0f}ms")

    output = {
        "timestamp": datetime.now().isoformat(),
        "test_type": "grounded_rag_targeted",
        "unique_questions": len(MESSAGES),
        "repeat_each": REPEAT_EACH,
        "total_tickets": results["total"],
        "success": results["success"],
        "failed": results["failed"],
        "success_rate": round(success_rate, 1),
        "total_time_seconds": round(total_time, 1),
        "throughput_rps": round(results["total"] / total_time, 1),
        "latency_ms": {
            "avg": round(avg),
            "p50": round(p50),
            "p95": round(p95),
            "p99": round(p99),
            "min": round(min(latencies)),
            "max": round(max(latencies))
        },
        "errors": results["errors"][:5]
    }

    with open("load_test_grounded_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to load_test_grounded_results.json")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
