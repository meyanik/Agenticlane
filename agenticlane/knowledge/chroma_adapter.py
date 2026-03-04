"""Lightweight ChromaDB query adapter for the chip design knowledge base.

Supports per-stage collections (chip_design_SYNTH, chip_design_CTS, etc.)
with a separate GENERAL collection. Falls back to a single-collection
mode if per-stage collections are not found.

Only exposes read operations (query, stats). Ingestion stays in RAG_PROJECT/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_STAGES = [
    "SYNTH",
    "FLOORPLAN",
    "PDN",
    "PLACE_GLOBAL",
    "PLACE_DETAILED",
    "CTS",
    "ROUTE_GLOBAL",
    "ROUTE_DETAILED",
    "FINISH",
    "SIGNOFF",
    "GENERAL",
]

COLLECTION_PREFIX = "chip_design_"
LEGACY_COLLECTION = "chip_design_knowledge"


class ChromaAdapter:
    """Read-only wrapper around per-stage ChromaDB collections.

    Each stage has its own collection (e.g. chip_design_CTS) plus a
    shared chip_design_GENERAL collection.  If per-stage collections
    are not found, falls back to the legacy single-collection mode
    with metadata filtering.
    """

    def __init__(
        self,
        db_path: str | Path,
        collection_name: str = LEGACY_COLLECTION,
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        import chromadb
        from chromadb.utils.embedding_functions import (
            SentenceTransformerEmbeddingFunction,
        )

        self._db_path = Path(db_path).resolve()
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"ChromaDB path does not exist: {self._db_path}"
            )

        self._client = chromadb.PersistentClient(path=str(self._db_path))
        self._ef = SentenceTransformerEmbeddingFunction(
            model_name=embedding_model,
        )

        # Detect mode: per-stage collections or legacy single collection
        existing_names = {c.name for c in self._client.list_collections()}
        has_per_stage = f"{COLLECTION_PREFIX}SYNTH" in existing_names

        if has_per_stage:
            self._mode = "per_stage"
            self._collections: dict[str, Any] = {}
            for stage in VALID_STAGES:
                cname = f"{COLLECTION_PREFIX}{stage}"
                if cname in existing_names:
                    self._collections[stage] = self._client.get_collection(
                        name=cname,
                        embedding_function=self._ef,  # type: ignore[arg-type]
                    )
            total = sum(
                c.count()  # type: ignore[union-attr]
                for c in self._collections.values()
            )
            logger.info(
                "ChromaAdapter [per-stage]: %s (%d collections, %d total chunks)",
                self._db_path,
                len(self._collections),
                total,
            )
        else:
            self._mode = "legacy"
            self._legacy_collection = self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=self._ef,  # type: ignore[arg-type]
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaAdapter [legacy]: %s (%d chunks)",
                self._db_path,
                self._legacy_collection.count(),
            )

    def query(
        self,
        query_text: str,
        stage: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, object]]:
        """Retrieve relevant chunks from the stage-specific collection.

        Returns list of dicts with keys: content, metadata, distance.
        """
        if self._mode == "per_stage":
            return self._query_per_stage(query_text, stage, top_k)
        return self._query_legacy(query_text, stage, top_k)

    def _query_per_stage(
        self,
        query_text: str,
        stage: str | None,
        top_k: int,
    ) -> list[dict[str, object]]:
        """Query the stage-specific collection."""
        if stage and stage in self._collections:
            collection = self._collections[stage]
        elif stage == "GENERAL" and "GENERAL" in self._collections:
            collection = self._collections["GENERAL"]
        else:
            # No matching collection; return empty
            return []

        results = collection.query(  # type: ignore[union-attr]
            query_texts=[query_text],
            n_results=top_k,
        )
        return self._parse_results(results)

    def _query_legacy(
        self,
        query_text: str,
        stage: str | None,
        top_k: int,
    ) -> list[dict[str, object]]:
        """Query the legacy single collection with metadata filter."""
        where: dict[str, str] | None = {"stage": stage} if stage else None

        results = self._legacy_collection.query(
            query_texts=[query_text],
            n_results=top_k,
            where=where,  # type: ignore[arg-type]
        )
        return self._parse_results(results)

    @staticmethod
    def _parse_results(results: Any) -> list[dict[str, object]]:
        """Convert ChromaDB query results to a flat list of dicts."""
        docs_outer = results.get("documents")
        if not docs_outer or not docs_outer[0]:  # type: ignore[index]
            return []

        output: list[dict[str, object]] = []
        docs = docs_outer[0]  # type: ignore[index]
        metas_outer = results.get("metadatas")
        dists_outer = results.get("distances")

        for i, doc in enumerate(docs):  # type: ignore[arg-type]
            meta = metas_outer[0][i] if metas_outer else {}  # type: ignore[index]
            dist = dists_outer[0][i] if dists_outer else None  # type: ignore[index]
            output.append({
                "content": doc,
                "metadata": meta,
                "distance": dist,
            })
        return output

    def get_stats(self) -> dict[str, int]:
        """Return chunk counts per stage."""
        stats: dict[str, int] = {}

        if self._mode == "per_stage":
            total = 0
            for stage, coll in self._collections.items():
                count = coll.count()  # type: ignore[union-attr]
                if count > 0:
                    stats[stage] = count
                    total += count
            stats["_total"] = total
        else:
            total = self._legacy_collection.count()
            if total == 0:
                return {"_total": 0}
            for stage in VALID_STAGES:
                result = self._legacy_collection.get(
                    where={"stage": stage},  # type: ignore[arg-type]
                    include=[],
                )
                count = len(result["ids"])
                if count > 0:
                    stats[stage] = count
            stats["_total"] = total

        stats["_mode"] = 0  # Marker: 0 = per_stage, 1 = legacy
        if self._mode == "legacy":
            stats["_mode"] = 1
        return stats
