"""Typed messages cho các agent PDF-vision của Direct_PDF_Mode.

Khác với `pipeline/agents/messages.py`: mỗi request mang `attachment_parts`
(danh sách part ảnh/file PDF đã dựng sẵn) thay cho `context: str`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PdfWriteRequest:
    attachment_parts: List[Dict[str, Any]]
    slot: Dict[str, Any]
    avoid_stems: List[str] = field(default_factory=list)
    num_samples: int = 1


@dataclass
class PdfWriteResponse:
    slot_id: str
    candidates: List[Dict[str, Any]]  # mỗi candidate có stem+answer+..., distractors=[]
    errors: List[str] = field(default_factory=list)


@dataclass
class PdfDistractorRequest:
    attachment_parts: List[Dict[str, Any]]
    candidate: Dict[str, Any]
    slot: Dict[str, Any]


@dataclass
class PdfDistractorResponse:
    distractors: List[Dict[str, Any]]
    error: Optional[str] = None


@dataclass
class PdfCriticRequest:
    attachment_parts: List[Dict[str, Any]]
    candidate: Dict[str, Any]
    slot: Dict[str, Any]


@dataclass
class PdfCriticResponse:
    annotations: Dict[str, Any]
    rejected: bool
    reject_reason: str = ''
