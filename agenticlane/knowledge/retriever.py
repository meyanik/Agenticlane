"""Knowledge retriever that queries ChromaDB and formats results for prompts."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from agenticlane.config.models import KnowledgeConfig
from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.knowledge import KnowledgeChunk, KnowledgeContext
from agenticlane.schemas.metrics import MetricsPayload

from .query_builder import build_query

logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """Retrieves domain knowledge from ChromaDB for agent prompts."""

    def __init__(self, config: KnowledgeConfig) -> None:
        from .chroma_adapter import ChromaAdapter

        self._config = config

        db_path = config.db_path
        if db_path is None:
            # Default: bundled DB inside the knowledge package
            db_path = Path(__file__).resolve().parent / "chroma_db"

        self._adapter = ChromaAdapter(
            db_path=db_path,
            collection_name=config.collection_name,
            embedding_model=config.embedding_model,
        )

    def retrieve(
        self,
        stage: str,
        metrics: MetricsPayload | None = None,
        evidence: EvidencePack | None = None,
        top_k: int | None = None,
    ) -> KnowledgeContext:
        """Query the knowledge base for the given stage context."""
        k = top_k or self._config.top_k
        query = build_query(stage, metrics, evidence)

        t0 = time.monotonic()
        raw_results = self._adapter.query(
            query_text=query,
            stage=stage,
            top_k=k,
        )
        # Also query GENERAL knowledge
        general_results = self._adapter.query(
            query_text=query,
            stage="GENERAL",
            top_k=max(1, k // 2),
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Merge and deduplicate
        all_results = raw_results + general_results
        seen_contents: set[str] = set()
        chunks: list[KnowledgeChunk] = []

        for r in all_results:
            content = str(r.get("content", ""))
            if content in seen_contents:
                continue
            seen_contents.add(content)

            raw_meta = r.get("metadata") or {}
            meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
            distance = r.get("distance")
            score = 1.0 - float(distance) if distance is not None else 0.0  # type: ignore[arg-type]

            if score < self._config.score_threshold:
                continue

            chunks.append(
                KnowledgeChunk(
                    content=content,
                    source=str(meta.get("source", "")),
                    stage=str(meta.get("stage", "")),
                    page_range=str(meta.get("page_range", "")),
                    heading=str(meta.get("heading", "")),
                    relevance_score=round(min(max(score, 0.0), 1.0), 4),
                )
            )

        # Sort by relevance, keep top_k
        chunks.sort(key=lambda c: c.relevance_score, reverse=True)
        chunks = chunks[:k]

        logger.info(
            "RAG retrieved %d chunks for stage=%s query=%s in %.0fms",
            len(chunks),
            stage,
            query[:80],
            elapsed_ms,
            extra={
                "event": "rag_retrieve",
                "stage": stage,
                "query": query[:200],
                "chunks_returned": len(chunks),
                "retrieval_ms": round(elapsed_ms, 1),
            },
        )

        return KnowledgeContext(
            chunks=chunks,
            query_used=query,
            retrieval_ms=round(elapsed_ms, 1),
        )

    @staticmethod
    def format_for_prompt(ctx: KnowledgeContext) -> str:
        """Render retrieved chunks as markdown for prompt injection."""
        if not ctx.chunks:
            return ""

        lines: list[str] = []
        for i, chunk in enumerate(ctx.chunks, 1):
            source_info = chunk.source
            if chunk.page_range:
                source_info += f" (pp. {chunk.page_range})"
            if chunk.heading:
                source_info += f" - {chunk.heading}"

            lines.append(f"### Reference {i} [{chunk.stage}] (relevance: {chunk.relevance_score:.0%})")
            lines.append(f"*Source: {source_info}*\n")
            lines.append(chunk.content)
            lines.append("")

        return "\n".join(lines)
