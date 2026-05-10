from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ParseStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"


class DecisionAction(str, Enum):
    MERGE = "merge"
    KEEP = "keep"
    REMOVE = "remove"


class DecisionStatus(str, Enum):
    ACTIVE = "active"
    OVERRIDDEN = "overridden"


@dataclass
class Chapter:
    title: str
    page_start: int
    page_end: int
    char_count: int
    text: str


@dataclass
class Textbook:
    filename: str
    status: ParseStatus = ParseStatus.PENDING
    chapters: list[Chapter] = field(default_factory=list)
    total_chars: int = 0
    total_pages: int = 0
    error: str = ""


@dataclass
class Chunk:
    chunk_id: str
    textbook: str
    chapter: str
    page: int
    text: str


@dataclass
class KnowledgeNode:
    name: str
    definition: str
    category: str
    chapter: str
    page: int
    textbook: str


@dataclass
class KnowledgeEdge:
    source: str
    target: str
    relation_type: str
    description: str


@dataclass
class IntegrationDecision:
    decision_id: str
    action: DecisionAction
    affected_nodes: list[str]
    result_node: str
    reason: str
    confidence: float
    status: DecisionStatus = DecisionStatus.ACTIVE
