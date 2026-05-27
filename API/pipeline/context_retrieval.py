"""Context retrieval — pick & expand relevant context per slot.

When grounding/quote fails, the orchestrator should try widening the context
window before re-asking the writer. This module provides:

    select_primary_context(dataset, slot)        — initial chunk's context
    expand_context(dataset, slot, attempt)       — wider context for retry
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from . import config as cfg
from .context_utils import strip_markdown


def _doc_clean(dataset: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    doc = dataset.get(doc_id) or {}
    return doc.get('clean_context') if isinstance(doc.get('clean_context'), dict) else {}


def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _tokens(text: str, min_len: int = 3) -> set[str]:
    folded = _fold(text)
    return {t for t in re.findall(rf'[a-z0-9]{{{min_len},}}', folded) if len(t) >= min_len}


def _doc_id_list(dataset: Dict[str, Any]) -> List[str]:
    return [
        k for k, v in dataset.items()
        if k != 'metadata' and isinstance(v, dict) and 'context' in v
    ]


def _doc_text(dataset: Dict[str, Any], doc_id: str) -> str:
    doc = dataset.get(doc_id) or {}
    clean = _doc_clean(dataset, doc_id)
    return clean.get('clean_text') or doc.get('context') or ''

def _runtime_context_unusable(text: str) -> bool:
    if not text.strip():
        return True
    private_use = sum(1 for ch in text if unicodedata.category(ch) == 'Co')
    private_ratio = private_use / max(1, len(text))
    alpha = sum(1 for ch in text if ch.isalpha())
    if private_ratio > 0.05:
        return True
    if private_ratio > 0.02 and alpha < 80:
        return True
    return False


def _doc_quality(dataset: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    clean = _doc_clean(dataset, doc_id)
    quality = clean.get('quality') if isinstance(clean.get('quality'), dict) else {}
    return quality


def _doc_type(dataset: Dict[str, Any], doc_id: str) -> str:
    return str(_doc_clean(dataset, doc_id).get('chunk_type') or 'theory')


def _preferred_types_for_slot(slot: Dict[str, Any]) -> set[str]:
    level = _fold(str(slot.get('cognitive_level') or ''))
    pattern = _fold(str(slot.get('question_pattern') or slot.get('meta_pattern') or ''))
    if 'van dung' in level or pattern in {'application', 'computation', 'reasoning'}:
        return {'theory', 'example'}
    return {'theory'}


def _type_penalty(dataset: Dict[str, Any], doc_id: str, slot: Dict[str, Any]) -> float:
    ctype = _doc_type(dataset, doc_id)
    preferred = _preferred_types_for_slot(slot)
    if ctype in preferred:
        return 0.0
    if ctype == 'example' and 'example' not in preferred:
        return 0.08
    if ctype == 'exercise':
        return 0.35
    return 0.15


def _is_unusable_context(dataset: Dict[str, Any], doc_id: str) -> Tuple[bool, str]:
    text = _doc_text(dataset, doc_id).strip()
    if not text:
        return True, 'context_missing'
    if _runtime_context_unusable(text):
        return True, 'context_too_noisy'
    quality = _doc_quality(dataset, doc_id)
    if quality:
        if quality.get('is_usable') is False:
            return True, 'context_missing'
        if quality.get('noise_level') == 'high':
            return True, 'context_too_noisy'
    return False, ''


def _format_clean_context(dataset: Dict[str, Any], doc_id: str) -> str:
    doc = dataset.get(doc_id) or {}
    clean = _doc_clean(dataset, doc_id)
    if not clean:
        return strip_markdown(doc.get('context') or '')
    parts: List[str] = []
    title = clean.get('title') or clean.get('topic') or doc.get('topic') or ''
    if title:
        parts.append(f'Topic: {title}')
    ctype = clean.get('chunk_type') or ''
    if ctype:
        parts.append(f'Chunk type: {ctype}')
        if ctype == 'exercise':
            parts.append('Anti-copy note: this chunk had existing exercises; use only formulas/concepts, not old stems/options.')
    for label, key in (
        ('Relevant formulas', 'key_formulas'),
        ('Key definitions', 'key_definitions'),
        ('Key theorems', 'key_theorems'),
        ('Worked examples', 'worked_examples'),
        ('Source quote candidates', 'source_spans'),
    ):
        items = [str(x).strip() for x in (clean.get(key) or []) if str(x).strip()]
        if items:
            parts.append(label + ':\n' + '\n'.join(f'- {item}' for item in items[:6]))
    text = clean.get('clean_text') or doc.get('context') or ''
    if text:
        parts.append('Clean context text:\n' + strip_markdown(text))
    return '\n\n'.join(parts).strip()


def _slot_keywords(slot: Dict[str, Any]) -> set[str]:
    parts: List[str] = [
        str(slot.get('topic') or ''),
        str(slot.get('skill') or ''),
        str(slot.get('cognitive_level') or ''),
    ]
    for raw in slot.get('inferred_misconceptions') or []:
        if isinstance(raw, dict):
            parts.append(str(raw.get('id', '')))
            parts.append(str(raw.get('wrong_form', '')))
    for ft in slot.get('_focus_topics') or []:
        parts.append(str(ft))
    return _tokens(' '.join(parts))


def _topic_overlap(slot: Dict[str, Any], context: str) -> float:
    kw = _slot_keywords(slot)
    if not kw:
        return 0.0
    tokens = _tokens(context)
    if not tokens:
        return 0.0
    return len(kw & tokens) / max(1, len(kw))


def _index_in_dataset(dataset: Dict[str, Any], doc_id: str) -> int:
    ids = _doc_id_list(dataset)
    try:
        return ids.index(doc_id)
    except ValueError:
        return -1


def _neighboring_chunks(dataset: Dict[str, Any], doc_id: str,
                        radius: int = 1) -> List[str]:
    """Return chunks immediately before/after the given doc_id (siblings)."""
    ids = _doc_id_list(dataset)
    idx = _index_in_dataset(dataset, doc_id)
    if idx < 0:
        return []
    out: List[str] = []
    for r in range(1, radius + 1):
        if idx - r >= 0:
            out.append(ids[idx - r])
        if idx + r < len(ids):
            out.append(ids[idx + r])
    return out


def select_primary_context(dataset: Dict[str, Any], slot: Dict[str, Any],
                           max_chars: Optional[int] = None) -> Tuple[str, List[str]]:
    """Return (context, used_chunk_ids) for the initial pass."""
    max_chars = max_chars or cfg.GENERATION_CONTEXT_MAX_CHARS
    doc_id = slot.get('doc_id') or ''
    if doc_id and _doc_type(dataset, doc_id) == 'exercise':
        alt_id = find_alternative_chunk(dataset, slot, [doc_id])
        if alt_id and _doc_type(dataset, alt_id) != 'exercise':
            doc_id = alt_id
    unusable, _ = _is_unusable_context(dataset, doc_id)
    if unusable:
        return '', [doc_id] if doc_id else []
    text = _format_clean_context(dataset, doc_id)
    return text[:max_chars], [doc_id] if doc_id else []


def expand_context(
    dataset: Dict[str, Any],
    slot: Dict[str, Any],
    attempt: int,
    max_chars: Optional[int] = None,
) -> Tuple[str, List[str], str]:
    """Return widened context + chunk ids + an action label.

    attempt 1 → primary chunk only (no expansion)
    attempt 2 → primary + immediate neighbors (radius=1)
    attempt 3 → primary + neighbors radius=2 + best topic-match chunk
    attempt ≥4 → fall back to primary (give up; orchestrator will mark slot)
    """
    primary_doc_id = slot.get('doc_id') or ''
    base_max = max_chars or cfg.GENERATION_CONTEXT_MAX_CHARS

    if attempt <= 1:
        unusable, reason = _is_unusable_context(dataset, primary_doc_id)
        if unusable:
            return '', [primary_doc_id] if primary_doc_id else [], reason
        text, ids = select_primary_context(dataset, slot, base_max)
        return text, ids, 'primary_context'

    expanded_max = max_chars or cfg.GENERATION_CONTEXT_EXPANDED_MAX_CHARS

    # collect chunk IDs to merge
    chunk_ids: List[str] = []
    if primary_doc_id:
        chunk_ids.append(primary_doc_id)

    if attempt == 2:
        chunk_ids.extend(_neighboring_chunks(dataset, primary_doc_id, radius=1))
        action = 'expand_neighbors_radius_1'
    else:
        chunk_ids.extend(_neighboring_chunks(dataset, primary_doc_id, radius=2))
        # plus the highest topic-overlap chunk not already included
        best_id, best_score = None, 0.0
        for did in _doc_id_list(dataset):
            if did in chunk_ids:
                continue
            score = _topic_overlap(slot, _doc_text(dataset, did)) - _type_penalty(dataset, did, slot)
            if score > best_score:
                best_score, best_id = score, did
        if best_id and best_score >= 0.05:
            chunk_ids.append(best_id)
        action = 'expand_neighbors_radius_2_plus_topic_match'

    # de-dup keep order
    seen = set()
    ordered: List[str] = []
    for cid in chunk_ids:
        if cid and cid not in seen:
            ordered.append(cid)
            seen.add(cid)

    # merge clean contexts; skip unusable neighbors but keep primary failure visible.
    # Avoid exercise chunks unless they are the only usable source left.
    parts: List[str] = []
    usable_ordered: List[str] = []
    primary_unusable, primary_reason = _is_unusable_context(dataset, primary_doc_id)
    usable_candidates: List[str] = []
    for cid in ordered:
        unusable, _ = _is_unusable_context(dataset, cid)
        if unusable:
            continue
        usable_candidates.append(cid)
    preferred = _preferred_types_for_slot(slot)
    preferred_candidates = [
        cid for cid in usable_candidates
        if _doc_type(dataset, cid) in preferred
    ]
    if preferred_candidates:
        usable_candidates = preferred_candidates
    elif any(_doc_type(dataset, cid) != 'exercise' for cid in usable_candidates):
        usable_candidates = [
            cid for cid in usable_candidates
            if _doc_type(dataset, cid) != 'exercise'
        ]
    for cid in usable_candidates:
        chunk_text = _format_clean_context(dataset, cid)
        if chunk_text:
            parts.append(chunk_text)
            usable_ordered.append(cid)
    merged = '\n\n---\n\n'.join(parts).strip()
    if not merged:
        return '', ordered, primary_reason or 'context_missing'
    return merged[:expanded_max], usable_ordered, action


def find_alternative_chunk(
    dataset: Dict[str, Any], slot: Dict[str, Any], used_doc_ids: List[str],
) -> Optional[str]:
    """Return the doc_id of the most topic-relevant chunk not yet tried."""
    best_id, best_score = None, 0.0
    for did in _doc_id_list(dataset):
        if did in used_doc_ids:
            continue
        score = _topic_overlap(slot, _doc_text(dataset, did)) - _type_penalty(dataset, did, slot)
        if score > best_score:
            best_id, best_score = did, score
    return best_id if best_score >= 0.05 else None
