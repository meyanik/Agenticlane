#!/usr/bin/env python3
"""Migrate single ChromaDB collection to per-stage collections.

Reads all chunks+embeddings from `chip_design_knowledge`, creates one
collection per stage (chip_design_SYNTH, chip_design_CTS, etc.),
and copies chunks with their pre-computed embeddings (no re-embedding).

Usage:
    python -m agenticlane.knowledge.migrate_collections [--db-path PATH]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

VALID_STAGES = [
    "SYNTH", "FLOORPLAN", "PDN",
    "PLACE_GLOBAL", "PLACE_DETAILED",
    "CTS",
    "ROUTE_GLOBAL", "ROUTE_DETAILED",
    "FINISH", "SIGNOFF",
    "GENERAL",
]

COLLECTION_PREFIX = "chip_design_"
SOURCE_COLLECTION = "chip_design_knowledge"


def migrate(db_path: Path, force: bool = False) -> None:
    """Run the migration."""
    import chromadb
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )

    print(f"Opening ChromaDB at: {db_path}")
    client = chromadb.PersistentClient(path=str(db_path))
    ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    # Check if source collection exists
    try:
        source = client.get_collection(
            name=SOURCE_COLLECTION,
            embedding_function=ef,  # type: ignore[arg-type]
        )
    except Exception:
        print(f"ERROR: Source collection '{SOURCE_COLLECTION}' not found!")
        sys.exit(1)

    total = source.count()
    print(f"Source collection: {SOURCE_COLLECTION} ({total:,} chunks)")

    # Check if migration already done
    existing = {c.name for c in client.list_collections()}
    target_names = {f"{COLLECTION_PREFIX}{s}" for s in VALID_STAGES}
    already_done = target_names & existing
    if already_done:
        print(f"\nWARNING: {len(already_done)} target collections already exist:")
        for name in sorted(already_done):
            coll = client.get_collection(name=name, embedding_function=ef)  # type: ignore[arg-type]
            print(f"  {name}: {coll.count()} chunks")
        if not force:
            response = input("\nDelete and recreate? [y/N]: ").strip().lower()
            if response != "y":
                print("Aborted.")
                sys.exit(0)
        for name in already_done:
            client.delete_collection(name=name)
            print(f"  Deleted: {name}")

    # Migrate each stage
    t0 = time.monotonic()
    total_migrated = 0

    for stage in VALID_STAGES:
        target_name = f"{COLLECTION_PREFIX}{stage}"
        print(f"\n--- {stage} ---")

        # Get all chunks for this stage from source
        result = source.get(
            where={"stage": stage},
            include=["documents", "metadatas", "embeddings"],
        )

        ids = result["ids"]
        docs = result["documents"] if result["documents"] is not None else []
        metas = result["metadatas"] if result["metadatas"] is not None else []
        embeds = result["embeddings"] if result["embeddings"] is not None else []

        if not ids:
            print(f"  No chunks for stage {stage}, skipping")
            continue

        print(f"  Found {len(ids):,} chunks")

        # Create target collection
        target = client.get_or_create_collection(
            name=target_name,
            embedding_function=ef,  # type: ignore[arg-type]
            metadata={"hnsw:space": "cosine"},
        )

        # Add in batches (ChromaDB limit ~5000 per add)
        has_docs = docs is not None and len(docs) > 0
        has_metas = metas is not None and len(metas) > 0
        has_embeds = embeds is not None and len(embeds) > 0

        batch_size = 1000
        for i in range(0, len(ids), batch_size):
            end = min(i + batch_size, len(ids))
            target.add(
                ids=ids[i:end],
                documents=docs[i:end] if has_docs else None,
                metadatas=metas[i:end] if has_metas else None,
                embeddings=embeds[i:end] if has_embeds else None,
            )

        count = target.count()
        total_migrated += count
        print(f"  Created: {target_name} ({count:,} chunks)")

    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 50}")
    print(f"Migration complete in {elapsed:.1f}s")
    print(f"Total migrated: {total_migrated:,} chunks across {len(VALID_STAGES)} collections")
    print(f"Source collection '{SOURCE_COLLECTION}' left intact")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Migrate to per-stage collections")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(__file__).resolve().parent / "chroma_db",
        help="Path to ChromaDB directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing target collections without prompting",
    )
    args = parser.parse_args()
    migrate(args.db_path, force=args.force)


if __name__ == "__main__":
    main()
