"""
VoltShop CX Agent — Final Mixed Load Test
500 tickets across all intent types at concurrency 20.
Realistic distribution — no cache clearing, mixed routes.
Usage: python scripts/load_test_mixed.py
"""

import httpx
import asyncio
import random
import uuid
import time
import json
from datetime import datetime

WEBHOOK_URL = "https://n8n-production-acb9.up.railway.app/webhook/ce7fb03a-8189-4574-b0fd-8cb1edbd5b09"
TOTAL_TICKETS = 500
CONCURRENCY = 20

# Realistic mixed message pool
# ~50% RAG grounded, ~20% ungrounded, ~15% escalation, ~10% order not found, ~5% refund
MESSAGES = [
    # RAG grounded — policy questions (40 unique)
    ("rag", "What is your return policy?"),
    ("rag", "How long does shipping take?"),
    ("rag", "What is your warranty policy?"),
    ("rag", "Do you offer international shipping?"),
    ("rag", "What payment methods do you accept?"),
    ("rag", "How do I track my order?"),
    ("rag", "What is your cancellation policy?"),
    ("rag", "Do you offer student discounts?"),
    ("rag", "What is the VoltShield warranty?"),
    ("rag", "How do I contact customer support?"),
    ("rag", "What laptops do you have in stock?"),
    ("rag", "Do you sell refurbished products?"),
    ("rag", "What is the restocking fee for returns?"),
    ("rag", "How long do refunds take to process?"),
    ("rag", "What items cannot be returned?"),
    ("rag", "Do you offer warranty on custom PCs?"),
    ("rag", "How do I initiate a return?"),
    ("rag", "Do you offer free shipping?"),
    ("rag", "What happens if I receive a damaged product?"),
    ("rag", "How long is the warranty on monitors?"),
    ("rag", "Can I cancel my order after placing it?"),
    ("rag", "What is your policy on opened software?"),
    ("rag", "How do I claim warranty?"),
    ("rag", "What is VoltShield 1 year extension price?"),
    ("rag", "How long does warranty replacement take?"),
    ("rag", "Can I return a used item?"),
    ("rag", "Do you offer gift cards?"),
    ("rag", "How is tax calculated?"),
    ("rag", "What are your best selling products?"),
    ("rag", "Do you offer full amount refunds?"),
    ("rag", "What are non-returnable items?"),
    ("rag", "Can damaged or defective items be returned?"),
    ("rag", "Whats your shipping timeframe?"),
    ("rag", "How soon orders are processed?"),
    ("rag", "What are your shipping restrictions?"),
    ("rag", "Can I refuse or return a package?"),
    ("rag", "My laptop wont turn on, what to do?"),
    ("rag", "Whats included in your custom pc?"),
    ("rag", "Whats voltshield?"),
    ("rag", "What voids the warranty?"),

    # RAG ungrounded — out of scope (10 unique)
    ("ungrounded", "What is the meaning of life?"),
    ("ungrounded", "Can you recommend a good restaurant near me?"),
    ("ungrounded", "Who won the World Cup last year?"),
    ("ungrounded", "What is the best programming language to learn?"),
    ("ungrounded", "Can you write me a poem?"),
    ("ungrounded", "What is the weather like today?"),
    ("ungrounded", "Tell me a joke"),
    ("ungrounded", "What stocks should I invest in?"),
    ("ungrounded", "How do I learn machine learning?"),
    ("ungrounded", "What is the capital of France?"),

    # Direct escalation (8 unique)
    ("escalation", "I need to speak to a human agent right now"),
    ("escalation", "I want to escalate this to a manager"),
    ("escalation", "This is unacceptable I demand to speak to someone"),
    ("escalation", "Get me a human representative immediately"),
    ("escalation", "I am extremely angry and need human help now"),
    ("escalation", "Connect me to your supervisor"),
    ("escalation", "I want to file a formal complaint right now"),
    ("escalation", "This AI is useless, give me a real person"),

    # Order not found (6 unique)
    ("order_not_found", "What is the status of my order #99999?"),
    ("order_not_found", "Where is my order #88888?"),
    ("order_not_found", "Can you check my order #77777?"),
    ("order_not_found", "Track my order #66666"),
    ("order_not_found", "I need an update on order #55555"),
    ("order_not_found", "What happened to my order #44444?"),

    # Refund no match (6 unique)
    ("refund_no_match", "I want a refund for my order #99999"),
    ("refund_no_match", "Please process a refund for order #88888"),
    ("refund_no_match", "Refund my order #77777 immediately"),
    ("refund_no_match", "I need a refund for order #66666"),
    ("refund_no_match", "Process refund for my order #55555"),
    ("refund_no_match", "I want my money back for order #44444"),
]

# Build weighted pool — RAG 50%, ungrounded 15%, escalation 15%, order 10%, refund 10%
def build_ticket_pool():
    pool = []
    rag = [(m, t) for t, m in MESSAGES if t == "rag"]
    ungrounded = [(m, t) for t, m in MESSAGES if t == "ungrounded"]
    escalation = [(m, t) for t, m in MESSAGES if t == "escalation"]
    order = [(m, t) for t, m in MESSAGES if t == "order_not_found"]
    refund = [(m, t) for t, m in MESSAGES if t == "refund_no_match"]

    for _ in range(TOTAL_TICKETS):
        r = random.random()
        if r < 0.50:
            pool.append(random.choice(rag))
        elif r < 0.65:
            pool.append(random.choice(ungrounded))
        elif r < 0.80:
            pool.append(random.choice(escalation))
        elif r < 0.90:
            pool.append(random.choice(order))
        else:
            pool.append(random.choice(refund))

    random.shuffle(pool)
    return pool

results = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "latencies": [],
    "errors": [],
}


async def send_ticket(client: httpx.AsyncClient, message: str, intent: str, idx: int) -> None:
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
            results["errors"].append({
                "idx": idx,
                "intent": intent,
                "status": response.status_code
            })

        if idx % 50 == 0:
            print(f"[{idx}/{TOTAL_TICKETS}] {response.status_code} — {latency:.0f}ms — [{intent}] {message[:40]}")

    except Exception as e:
        latency = (time.time() - start) * 1000
        results["latencies"].append(latency)
        results["total"] += 1
        results["failed"] += 1
        results["errors"].append({"idx": idx, "intent": intent, "error": str(e)})
        if idx % 50 == 0:
            print(f"[{idx}/{TOTAL_TICKETS}] ERROR — {str(e)[:50]}")


async def main():
    print(f"\n{'='*60}")
    print(f"VoltShop CX Agent — Final Mixed Load Test")
    print(f"Total tickets : {TOTAL_TICKETS}")
    print(f"Concurrency   : {CONCURRENCY}")
    print(f"Distribution  : 50% RAG | 15% ungrounded | 15% escalation | 10% order | 10% refund")
    print(f"Started       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    ticket_pool = build_ticket_pool()

    start_time = time.time()
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def send_with_semaphore(client, message, intent, idx):
        async with semaphore:
            await send_ticket(client, message, intent, idx)

    async with httpx.AsyncClient() as client:
        tasks = [
            send_with_semaphore(client, msg, intent, idx)
            for idx, (msg, intent) in enumerate(ticket_pool)
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
    print(f"Total sent     : {results['total']}")
    print(f"Successful     : {results['success']}")
    print(f"Failed         : {results['failed']}")
    print(f"Success rate   : {success_rate:.1f}%")
    print(f"Total time     : {total_time:.1f}s")
    print(f"Throughput     : {results['total']/total_time:.1f} req/s")
    print(f"Avg latency    : {avg:.0f}ms")
    print(f"p50 latency    : {p50:.0f}ms")
    print(f"p95 latency    : {p95:.0f}ms")
    print(f"p99 latency    : {p99:.0f}ms")
    print(f"Min latency    : {min(latencies):.0f}ms")
    print(f"Max latency    : {max(latencies):.0f}ms")

    if results["errors"]:
        print(f"\nFirst 5 errors:")
        for err in results["errors"][:5]:
            print(f"  [{err['idx']}] [{err.get('intent','?')}] {err.get('error', err.get('status','?'))}")

    output = {
        "timestamp": datetime.now().isoformat(),
        "test_type": "mixed_realistic",
        "distribution": "50% RAG | 15% ungrounded | 15% escalation | 10% order_not_found | 10% refund_no_match",
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

    with open("load_test_mixed_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to load_test_mixed_results.json")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
