"""
VoltShop Knowledge Base Ingestion Script
=========================================
Reads markdown files from knowledge-base/, chunks them,
generates embeddings via Google Gemini, and upserts into Qdrant.

Usage:
    pip install google-generativeai qdrant-client
    python scripts/ingest_knowledge_base.py

Prerequisites:
    - Qdrant running locally (docker compose up -d)
    - GEMINI_API_KEY set in environment or .env file
"""

import os
import uuid
import glob
import time
from pathlib import Path

from dotenv import load_dotenv
import google.generativeai as genai
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
)

# ---- Configuration ----
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "voltshop_kb")
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge-base"

# Chunking config
CHUNK_SIZE = 500  # characters (not tokens — simpler, good enough for Phase 0)
CHUNK_OVERLAP = 100

# Gemini embedding model
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSION = 3072  # gemini-embedding-001 outputs 3072 dimensions


def chunk_text(text: str, source: str) -> list[dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    # Split by double newline (paragraphs) first for cleaner boundaries
    paragraphs = text.split("\n\n")

    current_chunk = ""
    current_section = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Track section headers
        if para.startswith("## "):
            current_section = para.replace("## ", "").strip()

        # If adding this paragraph exceeds chunk size, save current and start new
        if len(current_chunk) + len(para) > CHUNK_SIZE and current_chunk:
            chunks.append({
                "text": current_chunk.strip(),
                "source": source,
                "section": current_section,
            })
            # Keep overlap from end of current chunk
            overlap_text = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else current_chunk
            current_chunk = overlap_text + "\n\n" + para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "text": current_chunk.strip(),
            "source": source,
            "section": current_section,
        })

    return chunks


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts using Gemini."""
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=texts,
        task_type="retrieval_document",
    )
    return result["embedding"]


def main():
    # --- Validate ---
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set. Add it to your .env file.")
        return

    genai.configure(api_key=GEMINI_API_KEY)

    # --- Connect to Qdrant ---
    print(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}...")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # --- Create collection (recreate if exists) ---
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        print(f"Collection '{COLLECTION_NAME}' exists. Recreating...")
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIMENSION,
            distance=Distance.COSINE,
        ),
    )
    print(f"Created collection '{COLLECTION_NAME}'")

    # --- Read and chunk all knowledge base files ---
    md_files = sorted(glob.glob(str(KNOWLEDGE_BASE_DIR / "*.md")))
    if not md_files:
        print(f"ERROR: No .md files found in {KNOWLEDGE_BASE_DIR}")
        return

    all_chunks = []
    for filepath in md_files:
        filename = Path(filepath).stem
        print(f"Processing: {filename}")
        with open(filepath, "r") as f:
            text = f.read()

        # Remove the H1 title line (first line starting with #)
        lines = text.split("\n")
        if lines and lines[0].startswith("# "):
            doc_title = lines[0].replace("# ", "").strip()
            text = "\n".join(lines[1:])
        else:
            doc_title = filename

        chunks = chunk_text(text, source=doc_title)
        all_chunks.extend(chunks)
        print(f"  → {len(chunks)} chunks")

    print(f"\nTotal chunks: {len(all_chunks)}")

    # --- Generate embeddings in batches ---
    print("Generating embeddings via Gemini...")
    batch_size = 20  # Gemini supports batching
    all_embeddings = []

    for i in range(0, len(all_chunks), batch_size):
        batch_texts = [c["text"] for c in all_chunks[i : i + batch_size]]
        embeddings = generate_embeddings(batch_texts)
        all_embeddings.extend(embeddings)
        print(f"  Embedded {min(i + batch_size, len(all_chunks))}/{len(all_chunks)}")
        time.sleep(0.5)  # Respect rate limits

    # --- Upsert into Qdrant ---
    print("Upserting into Qdrant...")
    points = []
    for idx, (chunk, embedding) in enumerate(zip(all_chunks, all_embeddings)):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "content": chunk["text"],
                    "source": chunk["source"],
                    "section": chunk["section"],
                },
            )
        )

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"Successfully upserted {len(points)} chunks into '{COLLECTION_NAME}'")

    # --- Verify ---
    collection_info = client.get_collection(COLLECTION_NAME)
    print(f"\nCollection '{COLLECTION_NAME}' stats:")
    print(f"  Points: {collection_info.points_count}")
    print(f"  Vectors size: {collection_info.config.params.vectors.size}")
    print(f"  Distance: {collection_info.config.params.vectors.distance}")
    print("\nDone! Knowledge base is ready for RAG.")


if __name__ == "__main__":
    main()
