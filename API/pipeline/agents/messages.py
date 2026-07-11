"""Typed messages for the Direct_PDF_Mode reusable agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FormatAcceptedRequest:
    slot: Dict[str, Any]
    candidate: Dict[str, Any]
    doc: Dict[str, Any]
    attempts: int = 1


@dataclass
class FormatRejectedRequest:
    slot: Dict[str, Any]
    slot_result: Any


@dataclass
class FormatResponse:
    record: Dict[str, Any]
    is_rejected: bool


@dataclass
class VerifyRequest:
    candidate: Dict[str, Any]
    slot: Dict[str, Any]
    context: str = ''


@dataclass
class VerifyResponse:
    annotations: Dict[str, Any]
    rejected: bool
    reject_reason: str = ''


@dataclass
class WriteRequest:
    slot: Dict[str, Any]
    context: str
    num_samples: int = 2
    feedback: List[str] = field(default_factory=list)


@dataclass
class WriteResponse:
    slot_id: str
    candidates: List[Dict[str, Any]]
    errors: List[str] = field(default_factory=list)


@dataclass
class DistractorRequest:
    candidate: Dict[str, Any]
    slot: Dict[str, Any]
    context: str = ''
    feedback: List[str] = field(default_factory=list)


@dataclass
class DistractorResponse:
    distractors: List[Dict[str, str]]
    error: Optional[str] = None
