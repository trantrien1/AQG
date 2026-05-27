"""Document-understanding skill implementations for preprocessing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_LONG_DOC_CHARS = 30_000
DEFAULT_TOO_LONG_CHARS = 120_000
DEFAULT_TARGET_CHARS = 3_500
DEFAULT_MAX_CHARS = 6_000
DEFAULT_MAX_UNITS = 40

HEADING_RE = re.compile(
    r'^\s*(?:Chương|CHƯƠNG|Chapter|Bài|BÀI|Mục|MỤC|Section)\s+\d+|'
    r'^\s*\d+(?:\.\d+){0,3}\s+[^\n]{3,120}$',
    re.IGNORECASE,
)
NOISE_RE = re.compile(
    r'^\s*(?:mục\s+lục|table\s+of\s+contents|tài\s+liệu\s+tham\s+khảo|'
    r'references|bibliography)\s*$',
    re.IGNORECASE,
)
KEY_RE = re.compile(
    r'\b(?:định\s+nghĩa|định\s+lý|hệ\s+quả|công\s+thức|ví\s+dụ|bài\s+tập|'
    r'lời\s+giải|đáp\s+án|definition|theorem|formula|example|exercise|answer|'
    r'dinh\s+nghia|cong\s+thuc|vi\s+du|bai\s+tap)\b|'
    r'[=+\-*/^√∑∫≤≥]|\\frac|\\sqrt',
    re.IGNORECASE,
)


def dataset_units(dataset: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    return [
        (k, v)
        for k, v in dataset.items()
        if k != 'metadata' and isinstance(v, dict) and 'context' in v
    ]


@dataclass
class DocumentClassificationSkill:
    def run(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        metadata = dataset.get('metadata') or {}
        source = str(metadata.get('source') or '').lower()
        text = '\n'.join(unit.get('context', '')[:2000] for _, unit in dataset_units(dataset)).lower()
        if any(k in text for k in ('bài tập', 'đáp án', 'exercise', 'bai tap')):
            doc_type = 'exercise_or_textbook'
        elif any(k in source or k in text for k in ('slide', 'lecture')):
            doc_type = 'slide'
        elif any(k in source or k in text for k in ('paper', 'abstract', 'references')):
            doc_type = 'paper'
        else:
            doc_type = 'general_math_document'
        return {'document_type': doc_type, 'source': metadata.get('source')}


@dataclass
class LongDocumentDetectionSkill:
    long_doc_chars: int = DEFAULT_LONG_DOC_CHARS
    too_long_chars: int = DEFAULT_TOO_LONG_CHARS

    def run(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        units = dataset_units(dataset)
        total_chars = sum(len(u.get('context', '')) for _, u in units)
        max_unit_chars = max((len(u.get('context', '')) for _, u in units), default=0)
        is_long = total_chars >= self.long_doc_chars or max_unit_chars >= self.long_doc_chars
        return {
            'total_chars': total_chars,
            'num_units': len(units),
            'max_unit_chars': max_unit_chars,
            'is_long': is_long,
            'is_too_long': total_chars >= self.too_long_chars,
            'long_doc_chars': self.long_doc_chars,
            'too_long_chars': self.too_long_chars,
            'warning': (
                'Tài liệu dài; việc xử lý toàn bộ có thể tăng thời gian chạy, chi phí token '
                'và làm giảm độ chính xác nếu đưa quá nhiều context vào LLM.'
                if is_long else None
            ),
        }


@dataclass
class NoiseRemovalSkill:
    def run(self, text: str) -> str:
        lines: List[str] = []
        for line in (text or '').splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append('')
                continue
            if NOISE_RE.match(stripped) or re.fullmatch(r'\d+', stripped):
                continue
            if stripped.count('.') > max(8, len(stripped) * 0.25):
                continue
            lines.append(stripped)
        cleaned = '\n'.join(lines)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
        return cleaned.strip()


@dataclass
class ChunkingSkill:
    target_chars: int = DEFAULT_TARGET_CHARS
    max_chars: int = DEFAULT_MAX_CHARS
    min_heading_break_chars: int = 600

    def run(self, dataset: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        counter = 0
        for old_id, unit in dataset_units(dataset):
            for idx, part in enumerate(self.split_text(unit.get('context', ''))):
                out.append({
                    'doc_id': f'prep_{counter:04d}',
                    'source_doc_id': old_id,
                    'part_index': idx,
                    'topic': (first_heading(part) or unit.get('topic') or old_id)[:140],
                    'pages': unit.get('pages', []),
                    'context': part,
                })
                counter += 1
        return out

    def split_text(self, text: str) -> List[str]:
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text or '') if p.strip()]
        chunks: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            nonlocal buf
            if buf:
                chunks.append('\n\n'.join(buf).strip())
                buf = []

        for para in paragraphs:
            first = para.splitlines()[0] if para.splitlines() else ''
            if HEADING_RE.search(first) and buf and sum(len(x) for x in buf) >= self.min_heading_break_chars:
                flush()
            if sum(len(x) for x in buf) + len(para) > self.max_chars:
                flush()
            if len(para) > self.max_chars:
                chunks.extend(split_long_paragraph(para, self.max_chars))
                continue
            buf.append(para)
            if sum(len(x) for x in buf) >= self.target_chars:
                flush()
        flush()
        return chunks


@dataclass
class KnowledgeExtractionSkill:
    summary_chars: int = 700
    max_key_extracts: int = 8

    def run(self, text: str) -> Dict[str, Any]:
        return {
            'summary': summarize_text(text, self.summary_chars),
            'key_extracts': extract_key_passages(text, self.max_key_extracts),
        }


@dataclass
class RelevanceFilteringSkill:
    max_units: int = DEFAULT_MAX_UNITS
    section_filter: Optional[str] = None

    def run(self, units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = units
        if self.section_filter:
            filtered = [u for u in units if self.section_filter.lower() in unit_search_text(u).lower()]
            if filtered:
                candidates = filtered
        selected = sorted(
            candidates,
            key=lambda u: score_unit(u, self.section_filter),
            reverse=True,
        )[:self.max_units]
        selected.sort(key=lambda u: (min(u.get('pages') or [0]), u['doc_id']))
        return selected


def split_long_paragraph(text: str, max_chars: int) -> List[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    parts: List[str] = []
    buf = ''
    for sent in sentences:
        if len(buf) + len(sent) + 1 > max_chars and buf:
            parts.append(buf.strip())
            buf = sent
        else:
            buf = f'{buf} {sent}'.strip()
    if buf:
        parts.append(buf.strip())
    return parts


def first_heading(text: str) -> Optional[str]:
    for line in (text or '').splitlines()[:12]:
        line = line.strip()
        if HEADING_RE.search(line):
            return line
    return None


def summarize_text(text: str, max_chars: int = 700) -> str:
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
    picked: List[str] = []
    for sent in sentences:
        s = re.sub(r'\s+', ' ', sent).strip()
        if len(s) < 12:
            continue
        if KEY_RE.search(s) or len(picked) < 2:
            picked.append(s)
        if len(' '.join(picked)) >= max_chars:
            break
    return ' '.join(picked)[:max_chars].strip()


def extract_key_passages(text: str, max_items: int = 8) -> List[str]:
    items: List[str] = []
    for line in re.split(r'\n+|(?<=[.!?])\s+', text):
        s = re.sub(r'\s+', ' ', line).strip()
        if 8 <= len(s) <= 320 and KEY_RE.search(s):
            items.append(s)
        if len(items) >= max_items:
            break
    return items


def score_unit(unit: Dict[str, Any], section_filter: Optional[str]) -> float:
    text = unit_search_text(unit)
    score = 5.0 * len(unit.get('key_extracts') or [])
    score += 3.0 if first_heading(text) else 0.0
    score += min(len(text) / 1000.0, 5.0)
    if section_filter and section_filter.lower() in text.lower():
        score += 100.0
    return score


def unit_search_text(unit: Dict[str, Any]) -> str:
    return '\n'.join([
        str(unit.get('topic', '')),
        str(unit.get('summary', '')),
        '\n'.join(unit.get('key_extracts') or []),
        str(unit.get('context', '')),
    ])
