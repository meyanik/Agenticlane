"""Knowledge retrieval schemas for RAG integration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    """A single retrieved knowledge chunk from the RAG database."""

    content: str
    source: str = ""
    stage: str = ""
    page_range: str = ""
    heading: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class KnowledgeContext(BaseModel):
    """Aggregated RAG retrieval result for injection into prompts."""

    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    query_used: str = ""
    retrieval_ms: float = 0.0
