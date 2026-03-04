"""Tests for KnowledgeRetriever with mocked ChromaDB adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticlane.config.models import KnowledgeConfig
from agenticlane.schemas.knowledge import KnowledgeChunk, KnowledgeContext
from agenticlane.schemas.metrics import MetricsPayload, TimingMetrics

# Patch target: where ChromaAdapter is imported in retriever.py
_ADAPTER_PATCH = "agenticlane.knowledge.chroma_adapter.ChromaAdapter"


class TestKnowledgeSchemas:
    """Schema validation tests."""

    def test_chunk_defaults(self) -> None:
        chunk = KnowledgeChunk(content="test")
        assert chunk.source == ""
        assert chunk.stage == ""
        assert chunk.relevance_score == 0.0

    def test_chunk_full(self) -> None:
        chunk = KnowledgeChunk(
            content="CTS buffer insertion",
            source="cts_guide.pdf",
            stage="CTS",
            page_range="10-15",
            heading="Buffer Insertion",
            relevance_score=0.85,
        )
        assert chunk.content == "CTS buffer insertion"
        assert chunk.relevance_score == 0.85

    def test_context_defaults(self) -> None:
        ctx = KnowledgeContext()
        assert ctx.chunks == []
        assert ctx.query_used == ""
        assert ctx.retrieval_ms == 0.0

    def test_context_with_chunks(self) -> None:
        ctx = KnowledgeContext(
            chunks=[KnowledgeChunk(content="a"), KnowledgeChunk(content="b")],
            query_used="test query",
            retrieval_ms=42.5,
        )
        assert len(ctx.chunks) == 2
        assert ctx.query_used == "test query"


def _make_mock_adapter(results: list[dict[str, object]] | None = None) -> MagicMock:
    """Create a mock ChromaAdapter with pre-configured query results."""
    adapter = MagicMock()
    if results is None:
        results = [
            {
                "content": "CTS best practice: keep skew under 100ps",
                "metadata": {
                    "source": "cts_guide.pdf",
                    "stage": "CTS",
                    "page_range": "10-15",
                    "heading": "Clock Tree Optimization",
                },
                "distance": 0.3,  # score = 0.7
            },
            {
                "content": "Use buffer insertion for long nets",
                "metadata": {
                    "source": "physical_design.pdf",
                    "stage": "CTS",
                    "page_range": "20-25",
                    "heading": "Buffer Strategy",
                },
                "distance": 0.5,  # score = 0.5
            },
            {
                "content": "Low relevance chunk",
                "metadata": {
                    "source": "misc.pdf",
                    "stage": "CTS",
                    "page_range": "1-2",
                    "heading": "Intro",
                },
                "distance": 0.8,  # score = 0.2 — below default threshold
            },
        ]
    adapter.query.return_value = results
    return adapter


class TestKnowledgeRetrieverWithMock:
    """Retriever tests using mocked ChromaAdapter."""

    @patch(_ADAPTER_PATCH)
    def test_retrieve_filters_by_score(
        self, mock_adapter_cls: MagicMock
    ) -> None:
        mock_adapter_cls.return_value = _make_mock_adapter()
        config = KnowledgeConfig(enabled=True, score_threshold=0.35)

        from agenticlane.knowledge.retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever(config)
        ctx = retriever.retrieve(stage="CTS")

        # Low relevance (0.2) should be filtered out
        for chunk in ctx.chunks:
            assert chunk.relevance_score >= 0.35

    @patch(_ADAPTER_PATCH)
    def test_retrieve_with_metrics(
        self, mock_adapter_cls: MagicMock
    ) -> None:
        mock_adapter_cls.return_value = _make_mock_adapter()
        config = KnowledgeConfig(enabled=True)

        from agenticlane.knowledge.retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever(config)
        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="CTS",
            attempt=1,
            execution_status="success",
            timing=TimingMetrics(setup_wns_ns={"nom": -0.5}),
        )
        ctx = retriever.retrieve(stage="CTS", metrics=metrics)

        assert "CTS" in ctx.query_used
        assert ctx.retrieval_ms >= 0

    @patch(_ADAPTER_PATCH)
    def test_retrieve_empty_results(
        self, mock_adapter_cls: MagicMock
    ) -> None:
        mock_adapter_cls.return_value = _make_mock_adapter(results=[])
        config = KnowledgeConfig(enabled=True)

        from agenticlane.knowledge.retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever(config)
        ctx = retriever.retrieve(stage="SYNTH")

        assert ctx.chunks == []
        assert ctx.query_used != ""

    @patch(_ADAPTER_PATCH)
    def test_retrieve_deduplicates(
        self, mock_adapter_cls: MagicMock
    ) -> None:
        """Duplicate content from stage + GENERAL queries should be deduplicated."""
        results = [
            {
                "content": "Same content twice",
                "metadata": {"source": "a.pdf", "stage": "CTS", "page_range": "1", "heading": "A"},
                "distance": 0.2,
            },
        ]
        mock_adapter_cls.return_value = _make_mock_adapter(results=results)
        config = KnowledgeConfig(enabled=True)

        from agenticlane.knowledge.retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever(config)
        ctx = retriever.retrieve(stage="CTS")

        contents = [c.content for c in ctx.chunks]
        assert len(contents) == len(set(contents))


class TestFormatForPrompt:
    """Prompt formatting tests."""

    def test_empty_context(self) -> None:
        from agenticlane.knowledge.retriever import KnowledgeRetriever

        ctx = KnowledgeContext()
        result = KnowledgeRetriever.format_for_prompt(ctx)
        assert result == ""

    def test_with_chunks(self) -> None:
        from agenticlane.knowledge.retriever import KnowledgeRetriever

        ctx = KnowledgeContext(
            chunks=[
                KnowledgeChunk(
                    content="CTS buffer insertion technique",
                    source="cts_guide.pdf",
                    stage="CTS",
                    page_range="10-15",
                    heading="Buffer Strategy",
                    relevance_score=0.75,
                ),
            ],
            query_used="CTS optimization",
        )
        result = KnowledgeRetriever.format_for_prompt(ctx)
        assert "Reference 1" in result
        assert "CTS buffer insertion" in result
        assert "cts_guide.pdf" in result
        assert "75%" in result

    def test_multiple_chunks(self) -> None:
        from agenticlane.knowledge.retriever import KnowledgeRetriever

        ctx = KnowledgeContext(
            chunks=[
                KnowledgeChunk(content="Chunk A", stage="CTS", relevance_score=0.9),
                KnowledgeChunk(content="Chunk B", stage="CTS", relevance_score=0.7),
            ],
        )
        result = KnowledgeRetriever.format_for_prompt(ctx)
        assert "Reference 1" in result
        assert "Reference 2" in result


class TestWorkerBackwardCompat:
    """Ensure existing worker code still works without rag_context."""

    @pytest.mark.asyncio
    async def test_propose_patch_without_rag(self) -> None:
        """WorkerAgent.propose_patch still works when rag_context is not provided."""
        from agenticlane.agents.workers.base import WorkerAgent
        from agenticlane.config.models import AgenticLaneConfig
        from agenticlane.schemas.evidence import EvidencePack
        from agenticlane.schemas.metrics import MetricsPayload
        from agenticlane.schemas.patch import Patch

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=Patch(
                patch_id="test",
                stage="SYNTH",
                types=["config_vars"],
                config_vars={"SYNTH_STRATEGY": "AREA 3"},
                rationale="test",
            )
        )
        config = AgenticLaneConfig()
        worker = WorkerAgent(mock_llm, "SYNTH", config)

        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="SYNTH",
            attempt=1,
            execution_status="success",
        )
        evidence = EvidencePack(
            stage="SYNTH", attempt=1, execution_status="success"
        )

        # Call without rag_context — should not raise
        result = await worker.propose_patch(
            current_metrics=metrics,
            evidence_pack=evidence,
        )
        assert result is not None
        assert result.patch_id == "test"

    @pytest.mark.asyncio
    async def test_propose_patch_with_rag(self) -> None:
        """WorkerAgent.propose_patch passes rag_context to template."""
        from agenticlane.agents.workers.base import WorkerAgent
        from agenticlane.config.models import AgenticLaneConfig
        from agenticlane.schemas.evidence import EvidencePack
        from agenticlane.schemas.metrics import MetricsPayload
        from agenticlane.schemas.patch import Patch

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=Patch(
                patch_id="rag_test",
                stage="CTS",
                types=["config_vars"],
                config_vars={},
                rationale="used RAG context",
            )
        )
        config = AgenticLaneConfig()
        worker = WorkerAgent(mock_llm, "CTS", config)

        metrics = MetricsPayload(
            run_id="r1",
            branch_id="B0",
            stage="CTS",
            attempt=1,
            execution_status="success",
        )
        evidence = EvidencePack(
            stage="CTS", attempt=1, execution_status="success"
        )

        result = await worker.propose_patch(
            current_metrics=metrics,
            evidence_pack=evidence,
            rag_context="## Domain Knowledge\nCTS best practice: keep skew under 100ps",
        )
        assert result is not None

        # Verify RAG context was included in the prompt sent to LLM
        call_kwargs = mock_llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") if call_kwargs.kwargs else ""
        assert "Domain Knowledge" in prompt or "keep skew" in prompt
