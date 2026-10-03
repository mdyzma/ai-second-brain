"""Pydantic models that form the public API contract (and the generated TS client)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_second_brain.chat.models import ChatMode, ChatSession, Turn


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    database: Literal["ok", "error"]


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


class MeResponse(BaseModel):
    authenticated: Literal[True]
    expires_at: datetime


MAX_QUESTION_LENGTH = 8000


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ChatMode = ChatMode.PRIVATE


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str

    @field_validator("question")
    @classmethod
    def _trimmed_length(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_QUESTION_LENGTH:
            raise ValueError("question must be 1-8000 characters after trimming")
        return value


class SessionDetail(ChatSession):
    turns: list[Turn]


class EndpointStatusOut(BaseModel):
    label: str
    model: str
    degraded: bool
    reachable: bool


class PrivateTierStatus(BaseModel):
    available: bool
    endpoints: list[EndpointStatusOut]


class CloudTierStatus(BaseModel):
    available: bool
    model: str | None


class ChatStatusResponse(BaseModel):
    private: PrivateTierStatus
    cloud: CloudTierStatus


class VaultState(BaseModel):
    configured: bool
    readable: bool


class SourceCounts(BaseModel):
    active: int
    deleted: int


class RevisionCounts(BaseModel):
    pending: int
    indexed: int
    failed: int


class EmbeddingState(BaseModel):
    model: str
    embedded: int
    total: int
    host_reachable: bool | None
    last_error: str | None


class JobCounts(BaseModel):
    waiting: int
    failed: int


class IngestRun(BaseModel):
    trigger: str
    started_at: datetime
    picked_up_at: datetime | None  # null: a manual run no worker has started yet
    finished_at: datetime | None
    outcome: str | None
    counts: dict[str, int]


class SourcesSummary(BaseModel):
    vault: VaultState
    sources: SourceCounts
    revisions: RevisionCounts
    chunks: int
    embedding: EmbeddingState
    jobs: JobCounts
    last_run: IngestRun | None


class SourceRow(BaseModel):
    id: UUID
    title: str | None
    path: str
    state: Literal["pending", "indexed", "failed", "superseded", "deleted"]
    error: str | None
    indexed_at: datetime | None
    chunks: int
    embedded: int


class SourceList(BaseModel):
    items: list[SourceRow]
    next_cursor: str | None


class ReconcileQueued(BaseModel):
    run_id: int


class SearchHit(BaseModel):
    source_id: UUID
    path: str
    title: str | None
    heading_path: list[str]
    snippet: str
    matched: list[Literal["text", "vector"]]
    score: float
    obsidian_url: str | None


class SearchResponse(BaseModel):
    vector: Literal["ok", "unavailable"]
    results: list[SearchHit]


class FolderFacet(BaseModel):
    path: str
    count: int


class TagFacet(BaseModel):
    tag: str
    count: int


class SearchFacets(BaseModel):
    folders: list[FolderFacet]
    tags: list[TagFacet]


class CaptureRequest(BaseModel):
    text: str = Field(max_length=20_000)


class CaptureResponse(BaseModel):
    path: str
    title: str
    obsidian_url: str | None


# --- knowledge graph (Phase 4a) ---

EntityType = Literal["project", "person", "organization", "tool", "device", "topic"]
EntityStatus = Literal["proposed", "accepted", "rejected"]
Relation = Literal["mentions", "about", "uses", "runs_on", "works_with", "part_of"]


class RevisionProgress(BaseModel):
    total: int
    extracted: int
    failed: int
    pending: int


class EntityStatusCounts(BaseModel):
    proposed: int
    accepted: int
    rejected: int


class GraphStatus(BaseModel):
    model: str | None
    extractor_version: str
    available: bool
    revisions: RevisionProgress
    entities: dict[str, EntityStatusCounts]  # by entity type; raw counts by entity status
    queued: int


class GraphExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["new", "failed"]


class ExtractQueued(BaseModel):
    queued: int


class EntityRef(BaseModel):
    id: UUID
    name: str
    type: EntityType


class NoteSample(BaseModel):
    path: str
    title: str | None
    summary: str | None
    obsidian_url: str | None


class EntitySuggestion(BaseModel):
    id: UUID
    name: str
    similarity: float


class ReviewEntity(BaseModel):
    id: UUID
    name: str
    type: EntityType
    aliases: list[str]
    mention_count: int
    samples: list[NoteSample]
    suggestion: EntitySuggestion | None


class ReviewEntityPage(BaseModel):
    items: list[ReviewEntity]
    next_cursor: str | None


class EntityDecision(BaseModel):
    """``action`` is accept, reject, rename (name), retype (type), parent (parent_id, null
    clears) or merge (into_id). An unknown action or a missing argument is invalid_action."""

    model_config = ConfigDict(extra="forbid")
    action: str = Field(max_length=32)
    name: str | None = Field(default=None, max_length=1000)
    type: str | None = Field(default=None, max_length=32)
    parent_id: UUID | None = None
    into_id: UUID | None = None


class LinkNote(BaseModel):
    source_id: UUID
    path: str
    title: str | None


class LinkEvidence(BaseModel):
    path: str
    heading: str | None
    obsidian_url: str | None


class ReviewLink(BaseModel):
    """kind ``relation``: ``subject`` is the source entity and ``note`` is null.
    kind ``mention``: ``note`` is the note and ``subject`` is null."""

    id: UUID
    kind: Literal["relation", "mention"]
    subject: EntityRef | None
    note: LinkNote | None
    relation: Relation
    object: EntityRef
    confidence: float
    evidence: LinkEvidence | None


class ReviewLinkPage(BaseModel):
    items: list[ReviewLink]
    next_cursor: str | None


class LinkDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    decision: Literal["accept", "reject"]


class LinkDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[LinkDecision] = Field(max_length=100)


class LinksUpdated(BaseModel):
    updated: int


class EntitySummary(BaseModel):
    id: UUID
    name: str
    type: EntityType
    note_count: int


class EntityPage(BaseModel):
    items: list[EntitySummary]
    next_cursor: str | None


class RelatedEntity(BaseModel):
    relation: Relation
    direction: Literal["out", "in"]  # out: this entity is the source; in: it is the target
    entity: EntityRef


class EntityNote(BaseModel):
    source_id: UUID
    path: str
    title: str | None
    summary: str | None
    heading: str | None
    relation: Relation
    obsidian_url: str | None


class EntityDetail(BaseModel):
    id: UUID
    name: str
    type: EntityType
    status: EntityStatus
    aliases: list[str]
    parent: EntityRef | None
    children: list[EntityRef]
    related: list[RelatedEntity]
    notes: list[EntityNote]


class EntityDecided(BaseModel):
    entity: EntityDetail
