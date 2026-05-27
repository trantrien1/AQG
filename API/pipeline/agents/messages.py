"""Typed messages cho inter-agent communication."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ==== Ingestion ====

@dataclass
class IngestionRequest:
    pdf_path: str
    target_chars: int = 1000
    filter_low_quality: bool = True
    chunk_page_threshold: int = 100
    force_chunk: bool = False
    preprocess_long_documents: bool = True
    long_doc_chars: int = 30000
    too_long_doc_chars: int = 120000
    max_context_units: int = 40
    section_filter: Optional[str] = None
    allow_very_long: bool = False


@dataclass
class IngestionResponse:
    dataset: Dict[str, Any]
    num_chunks: int
    source_name: str
    error: Optional[str] = None
    preprocessing_report: Optional[Dict[str, Any]] = None


# ==== Planning ====

@dataclass
class PlanRequest:
    dataset: Dict[str, Any]
    num_questions: int
    seed: int = 42
    difficulty_distribution: Optional[List[Dict[str, Any]]] = None


@dataclass
class PlanResponse:
    slots: List[Dict[str, Any]]
    summary: Dict[str, Any]


# ==== Formatting ====

@dataclass
class FormatAcceptedRequest:
    slot: Dict[str, Any]
    candidate: Dict[str, Any]
    doc: Dict[str, Any]
    attempts: int = 1


@dataclass
class FormatRejectedRequest:
    slot: Dict[str, Any]
    slot_result: Any  # SlotResult


@dataclass
class FormatResponse:
    record: Dict[str, Any]
    is_rejected: bool


# ==== Rendering ====

@dataclass
class RenderRequest:
    records: List[Dict[str, Any]]
    out_dir: str


@dataclass
class RenderResponse:
    rendered_count: int
    skipped_count: int = 0
    error: Optional[str] = None


@dataclass
class VerifyRequest:
    candidate: Dict[str, Any]
    slot: Dict[str, Any]


@dataclass
class VerifyResponse:
    """annotations: các key bắt đầu bằng _ để merge vào candidate sau."""
    annotations: Dict[str, Any]
    rejected: bool
    reject_reason: str = ''


@dataclass
class CriticRequest:
    candidate: Dict[str, Any]
    context: str
    topic: str
    cognitive_level: str


@dataclass
class CriticResponse:
    annotations: Dict[str, Any]
    rejected: bool
    reject_reason: str = ''


@dataclass
class SlotResult:
    slot_id: str
    chosen: Optional[Dict[str, Any]]
    reject_log: List[str] = field(default_factory=list)
    attempts: int = 1


# ==== Stage 1/2 split: Writer + Distractor ====

@dataclass
class WriteRequest:
    slot: Dict[str, Any]
    context: str
    num_samples: int = 2
    feedback: List[str] = field(default_factory=list)


@dataclass
class WriteResponse:
    slot_id: str
    candidates: List[Dict[str, Any]]   # mỗi candidate có stem+answer+reasoning, distractors=[]
    errors: List[str] = field(default_factory=list)


@dataclass
class DistractorRequest:
    candidate: Dict[str, Any]    # output từ Writer (chưa có distractor)
    slot: Dict[str, Any]
    context: str = ''
    feedback: List[str] = field(default_factory=list)


@dataclass
class DistractorResponse:
    distractors: List[Dict[str, str]]   # 3 distractor đã parse
    error: Optional[str] = None


# ==== Fast Mode: merged Generator ====

@dataclass
class GenerateRequest:
    slot: Dict[str, Any]
    context: str
    num_samples: int = 1


@dataclass
class GenerateResponse:
    slot_id: str
    candidates: List[Dict[str, Any]]
    errors: List[str] = field(default_factory=list)


# ==== Refiner ====

@dataclass
class RefineRequest:
    candidate: Dict[str, Any]
    critique_traits: Dict[str, Dict[str, Any]]   # output từ multi-trait critic


@dataclass
class RefineResponse:
    candidate: Dict[str, Any]
    error: Optional[str] = None
