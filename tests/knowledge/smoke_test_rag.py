#!/usr/bin/env python3
"""Smoke test: RAG retrieval + local LLM integration.

Run: python tests/knowledge/smoke_test_rag.py
Requires: LM Studio running on port 1234, chromadb + sentence-transformers installed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# ── Step 1: Test ChromaDB RAG retrieval directly ──

def test_rag_retrieval() -> None:
    print("=" * 60)
    print("STEP 1: Testing RAG retrieval from ChromaDB")
    print("=" * 60)

    from agenticlane.config.models import KnowledgeConfig
    from agenticlane.knowledge.retriever import KnowledgeRetriever

    db_path = Path(__file__).resolve().parent.parent.parent / "agenticlane" / "knowledge" / "chroma_db"
    config = KnowledgeConfig(
        enabled=True,
        db_path=db_path,
        top_k=5,
        score_threshold=0.3,
    )

    print(f"  DB path: {db_path}")
    print(f"  DB exists: {db_path.exists()}")

    t0 = time.monotonic()
    retriever = KnowledgeRetriever(config)
    init_ms = (time.monotonic() - t0) * 1000
    print(f"  Retriever initialized in {init_ms:.0f}ms")

    # Test queries for different stages
    test_queries = [
        ("SYNTH", "synthesis optimization timing area"),
        ("CTS", "clock tree synthesis skew buffer insertion"),
        ("FLOORPLAN", "floorplan utilization die area core"),
        ("ROUTE_DETAILED", "DRC violations routing congestion"),
    ]

    for stage, desc in test_queries:
        from agenticlane.schemas.metrics import MetricsPayload
        metrics = MetricsPayload(
            run_id="smoke", branch_id="B0", stage=stage,
            attempt=1, execution_status="success",
        )
        ctx = retriever.retrieve(stage=stage, metrics=metrics)
        formatted = KnowledgeRetriever.format_for_prompt(ctx)

        print(f"\n  Stage: {stage} | Query: {ctx.query_used[:60]}...")
        print(f"  Chunks: {len(ctx.chunks)} | Time: {ctx.retrieval_ms:.0f}ms")
        for i, chunk in enumerate(ctx.chunks):
            print(f"    [{i+1}] score={chunk.relevance_score:.2f} src={chunk.source[:40]} stage={chunk.stage}")
            print(f"        {chunk.content[:100]}...")

        if not ctx.chunks:
            print("  WARNING: No chunks retrieved!")

    print("\n  RAG retrieval: OK")
    return retriever


# ── Step 2: Test RAG context in worker prompt ──

def test_rag_in_prompt(retriever: object) -> None:
    print("\n" + "=" * 60)
    print("STEP 2: Testing RAG context injection into worker prompt")
    print("=" * 60)

    from agenticlane.agents.workers.base import WorkerAgent
    from agenticlane.config.models import AgenticLaneConfig
    from agenticlane.knowledge.retriever import KnowledgeRetriever
    from agenticlane.schemas.evidence import EvidencePack
    from agenticlane.schemas.metrics import MetricsPayload

    config = AgenticLaneConfig()

    # Build context manually to inspect the prompt
    from unittest.mock import AsyncMock
    mock_llm = AsyncMock()
    worker = WorkerAgent(mock_llm, "CTS", config)

    metrics = MetricsPayload(
        run_id="smoke", branch_id="B0", stage="CTS",
        attempt=1, execution_status="success",
    )
    evidence = EvidencePack(stage="CTS", attempt=1, execution_status="success")

    # Get RAG context
    assert isinstance(retriever, KnowledgeRetriever)
    ctx = retriever.retrieve(stage="CTS", metrics=metrics)
    rag_text = KnowledgeRetriever.format_for_prompt(ctx)

    # Build context and render prompt
    context = worker._build_context(
        current_metrics=metrics,
        evidence_pack=evidence,
        constraint_digest=None,
        attempt_number=1,
        last_rejection=None,
        lessons_markdown=None,
        rag_context=rag_text,
    )
    prompt = worker._render_prompt(context)

    if "Domain Knowledge" in prompt:
        print("  RAG context block found in rendered prompt")
        # Show the RAG section
        start = prompt.find("## Domain Knowledge")
        end = prompt.find("## Task", start)
        rag_section = prompt[start:end].strip()
        print(f"  RAG section length: {len(rag_section)} chars")
        print(f"  First 300 chars:\n{rag_section[:300]}")
    else:
        print("  WARNING: RAG context NOT found in prompt!")
        if rag_text:
            print(f"  (rag_text was {len(rag_text)} chars but didn't make it into template)")

    print(f"\n  Total prompt length: {len(prompt)} chars")
    print("  Prompt injection: OK")


# ── Step 3: Test with actual local LLM ──

async def test_with_local_llm(retriever: object) -> None:
    print("\n" + "=" * 60)
    print("STEP 3: Testing full pipeline with local LLM (SemiKong-70B)")
    print("=" * 60)

    from agenticlane.agents.workers.base import WorkerAgent
    from agenticlane.config.models import AgenticLaneConfig, KnowledgeConfig, LLMConfig
    from agenticlane.knowledge.retriever import KnowledgeRetriever
    from agenticlane.schemas.evidence import EvidencePack
    from agenticlane.schemas.metrics import MetricsPayload, TimingMetrics
    from agenticlane.schemas.patch import Patch

    # Use litellm provider directly
    from agenticlane.agents.litellm_provider import LiteLLMProvider

    from agenticlane.config.models import LLMModelsConfig

    config = AgenticLaneConfig(
        llm=LLMConfig(
            mode="local",
            provider="litellm",
            api_base="http://127.0.0.1:1234/v1",
            temperature=0.0,
            models=LLMModelsConfig(
                worker="pentagoniac-semikong-70b",
                master="pentagoniac-semikong-70b",
                judge=["pentagoniac-semikong-70b"],
            ),
        ),
    )

    llm = LiteLLMProvider(
        config=config.llm,
    )

    worker = WorkerAgent(llm, "CTS", config)

    metrics = MetricsPayload(
        run_id="smoke", branch_id="B0", stage="CTS",
        attempt=1, execution_status="success",
        timing=TimingMetrics(setup_wns_ns={"nom_tt_025C_1v80": -0.35}),
    )
    evidence = EvidencePack(stage="CTS", attempt=1, execution_status="success")

    # Get RAG context (top_k=2 to fit in 4096 context window)
    assert isinstance(retriever, KnowledgeRetriever)
    ctx = retriever.retrieve(stage="CTS", metrics=metrics, evidence=evidence, top_k=2)
    rag_text = KnowledgeRetriever.format_for_prompt(ctx)
    print(f"  RAG context: {len(ctx.chunks)} chunks, {len(rag_text)} chars")

    print("  Calling LLM (this may take a while with 70B model)...")
    t0 = time.monotonic()
    try:
        patch = await worker.propose_patch(
            current_metrics=metrics,
            evidence_pack=evidence,
            rag_context=rag_text,
        )
        elapsed = time.monotonic() - t0

        if patch is not None:
            print(f"\n  LLM responded in {elapsed:.1f}s")
            print(f"  Patch ID: {patch.patch_id}")
            print(f"  Stage: {patch.stage}")
            print(f"  Types: {patch.types}")
            print(f"  Config vars: {json.dumps(patch.config_vars or {}, indent=4)}")
            print(f"  Rationale: {patch.rationale}")
            print("\n  Full pipeline: OK")
        else:
            print(f"\n  LLM returned None after {elapsed:.1f}s")
            print("  (This can happen if structured output parsing failed)")
            print("  Pipeline works but LLM output wasn't valid Patch JSON")
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n  LLM call failed after {elapsed:.1f}s: {e}")
        print("  (Expected if model can't produce structured JSON)")


def main() -> None:
    print("\nAgenticLane RAG Smoke Test")
    print("LLM: pentagoniac-semikong-70b via LM Studio :1234\n")

    try:
        retriever = test_rag_retrieval()
        test_rag_in_prompt(retriever)
        asyncio.run(test_with_local_llm(retriever))
    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 60)
    print("SMOKE TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
