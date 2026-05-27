"""Context preparation helpers for generation prompts.

Chunking and heading detection may keep markdown markers, but the Writer and
Distractor prompts should see plain text so copied source quotes align with the
normalised grounding matcher.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List

_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(
    r'^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$'
)

_BULLET_RE = re.compile(r'^\s*(?:[-+*]|\d+[.)])\s+')

_RELEVANCE_MARKERS = (
    'dinh nghia', 'duoc goi la', 'ky hieu', 'cong thuc', 'vi du',
    'loi giai', 'nguyen ly', 'quy tac', 'dinh ly', 'he qua',
    'formula', 'definition', 'example',
)

_STOPWORDS = {
    'mot', 'cac', 'nhung', 'duoc', 'khong', 'cho', 'voi', 'khi', 'thi',
    'la', 'cua', 'trong', 'neu', 'theo', 'hoi', 'hay', 'tinh', 'so',
    'bai', 'toan', 'pattern', 'conceptual', 'computation', 'reasoning',
    'application',
}


def strip_markdown(text: str) -> str:
    """Return a plain-text version of markdown-ish PDF context."""
    if not text:
        return ''

    s = str(text).replace('\r\n', '\n').replace('\r', '\n')

    # Remove deliberately omitted image placeholders before unwrapping emphasis.
    s = re.sub(r'\*\*?\s*==>\s*picture\b.*?<==\s*\*\*?', ' ', s, flags=re.I)
    s = re.sub(r'==>\s*picture\b.*?<==', ' ', s, flags=re.I)

    # Headings, code, links/images.
    s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s, flags=re.MULTILINE)
    s = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', s)
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)

    # Unwrap common emphasis markers. Keep plain multiplication symbols such as
    # "a * b" by only touching paired markdown spans.
    for _ in range(3):
        prev = s
        s = re.sub(r'(?<!\*)\*\*([^\n*][\s\S]*?[^\n*])\*\*(?!\*)', r'\1', s)
        s = re.sub(r'(?<!_)__([^\n_][\s\S]*?[^\n_])__(?!_)', r'\1', s)
        s = re.sub(r'(?<!\*)\*([^\n*][^*\n]*?[^\n*])\*(?!\*)', r'\1', s)
        s = re.sub(r'(?<!_)_([^\n_][^_\n]*?[^\n_])_(?!_)', r'\1', s)
        if s == prev:
            break

    lines: List[str] = []
    for raw_line in s.split('\n'):
        line = raw_line.strip()
        if not line:
            lines.append('')
            continue
        if _MARKDOWN_TABLE_SEPARATOR_RE.match(line):
            continue
        if '|' in line:
            line = line.strip('|')
            line = re.sub(r'\s*\|\s*', ' ', line)
        line = _BULLET_RE.sub('', line)
        lines.append(line)

    s = '\n'.join(lines)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = re.sub(r'\s+([,.;:)\]}])', r'\1', s)
    s = re.sub(r'([({\[])\s+', r'\1', s)
    return s.strip()


def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r'[a-z0-9]{3,}', _fold(text))
        if token not in _STOPWORDS
    }


def _slot_keywords(slot: Dict[str, Any]) -> set[str]:
    parts: List[str] = [
        str(slot.get('topic', '')),
        str(slot.get('skill', '')),
        str(slot.get('question_pattern', '')),
        str(slot.get('cognitive_level', '')),
    ]
    for raw in slot.get('inferred_misconceptions') or []:
        if isinstance(raw, dict):
            parts.append(str(raw.get('id', '')))
            parts.append(str(raw.get('wrong_form', '')))
            parts.append(str(raw.get('rationale', '')))
    return _tokens(' '.join(parts))


def _split_units(text: str) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
    units: List[str] = []
    for para in paragraphs:
        if len(para) <= 650:
            units.append(para)
            continue
        sentences = [
            s.strip() for s in re.split(r'(?<=[.!?])\s+', para)
            if s.strip()
        ]
        if len(sentences) <= 1:
            for start in range(0, len(para), 500):
                units.append(para[start:start + 650].strip())
            continue
        buf = ''
        for sent in sentences:
            if buf and len(buf) + 1 + len(sent) > 650:
                units.append(buf.strip())
                buf = sent
            else:
                buf = f'{buf} {sent}'.strip()
        if buf:
            units.append(buf.strip())
    return units


def _score_unit(unit: str, keywords: Iterable[str]) -> float:
    folded = _fold(unit)
    unit_tokens = _tokens(unit)
    score = 0.0
    keyword_set = set(keywords)
    if keyword_set:
        score += 5.0 * len(unit_tokens & keyword_set)
    score += 3.0 * sum(1 for marker in _RELEVANCE_MARKERS if marker in folded)
    score += min(4.0, len(re.findall(r'(?:[=<>]|<=|>=|\bC\s*\(|\bn!|\^|\bmod\b)', unit)))
    score += min(2.0, len(re.findall(r'\d', unit)) / 4.0)
    if 60 <= len(unit) <= 420:
        score += 0.5
    return score


def trim_context_for_generation(
    context: str,
    slot: Dict[str, Any] | None = None,
    max_chars: int = 1500,
) -> str:
    """Strip markdown and keep the most relevant <= max_chars plain-text context."""
    clean = strip_markdown(context)
    if not clean or len(clean) <= max_chars:
        return clean

    slot = slot or {}
    keywords = _slot_keywords(slot)
    units = _split_units(clean)
    if not units:
        return clean[:max_chars].rstrip()

    scored = [
        (idx, _score_unit(unit, keywords), unit)
        for idx, unit in enumerate(units)
    ]
    top = sorted(scored, key=lambda item: (-item[1], item[0]))
    selected: List[tuple[int, str]] = []
    budget = 0
    for idx, score, unit in top:
        if score <= 0 and selected:
            continue
        extra = len(unit) + (2 if selected else 0)
        if budget + extra > max_chars:
            continue
        selected.append((idx, unit))
        budget += extra
        if budget >= max_chars * 0.85:
            break

    # If scoring was too sparse, prepend from the original opening context.
    if budget < max_chars * 0.45:
        for idx, unit in scored:
            if any(idx == old_idx for old_idx, _ in selected):
                continue
            extra = len(unit) + (2 if selected else 0)
            if budget + extra > max_chars:
                continue
            selected.append((idx, unit))
            budget += extra
            if budget >= max_chars * 0.85:
                break

    if not selected:
        return clean[:max_chars].rstrip()

    ordered = [unit for _, unit in sorted(selected, key=lambda item: item[0])]
    out = '\n\n'.join(ordered).strip()
    return out[:max_chars].rstrip()

