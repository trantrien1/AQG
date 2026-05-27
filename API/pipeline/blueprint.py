"""Question Planner — Blueprint (mục 8) — phiên bản Toán chung.

Nguyên tắc (theo feedback user):
- Planner LLM-driven: pattern/skill/misconception được suy luận từ context bằng
  LLM (xem `slot_inference.py`), KHÔNG keyword-match vào danh sách hardcoded.
- Hardcoded `QUESTION_PATTERNS` chỉ là fallback khi không có API key/LLM lỗi.
- Phân bố mức nhận thức theo `difficulty_distribution`.
- Sample chunk theo round-robin để mọi tài liệu đều có ≥1 câu (nếu có thể).
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from . import slot_inference
from .pdf_parser import infer_topic_from_context


PATTERN_REPEAT_LIMIT = 3


_WORD_CHAR = r'A-Za-zÀ-ỹĐđ0-9_'


def _keyword_matches(topic_lower: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    pattern = rf'(?<![{_WORD_CHAR}]){re.escape(kw)}(?![{_WORD_CHAR}])'
    return re.search(pattern, topic_lower, flags=re.IGNORECASE) is not None


def _keyword_count(text_lower: str, keyword: str) -> int:
    kw = keyword.lower().strip()
    if not kw:
        return 0
    pattern = rf'(?<![{_WORD_CHAR}]){re.escape(kw)}(?![{_WORD_CHAR}])'
    return len(re.findall(pattern, text_lower, flags=re.IGNORECASE))


def _patterns_matching_topic(patterns: List[Any], topic: str,
                             context: str = '') -> List[str]:
    """Return pattern ids whose keywords match topic/context.

    Long no-chunk documents may contain many incidental keywords. Score matches
    instead of treating every hit equally, so dominant local concepts win over
    one-off words elsewhere in the document.
    """
    if not topic and not context:
        return [p['id'] if isinstance(p, dict) else p for p in patterns]
    topic_lower = topic.lower()
    context_lower = context.lower()
    scored: List[tuple[str, float]] = []
    generic: List[str] = []
    for p in patterns:
        if isinstance(p, str):
            generic.append(p)
            continue
        kws = p.get('keywords') or []
        if not kws:
            generic.append(p['id'])
            continue
        topic_hits = sum(_keyword_count(topic_lower, kw) for kw in kws)
        context_hits = sum(_keyword_count(context_lower, kw) for kw in kws)
        score = topic_hits * 8 + min(context_hits, 8)
        if score > 0:
            scored.append((p['id'], float(score)))

    if not scored:
        return generic

    max_score = max(score for _, score in scored)
    # Keep only reasonably strong matches. This avoids false positives from a
    # single "phương trình" or "nghiệm" inside a long single-document context.
    cutoff = max(1.0, max_score * 0.45)
    matched = [pid for pid, score in scored if score >= cutoff]
    return matched if matched else [pid for pid, _ in scored]


def _difficulty_split(total: int, dist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trả về list cùng độ dài với dist, gán `count` cho mỗi mức theo fraction."""
    fractions = [d.get('fraction', 0) for d in dist]
    s = sum(fractions) or 1.0
    counts = [int(round(total * f / s)) for f in fractions]
    delta = total - sum(counts)
    if delta != 0:
        idx = sorted(range(len(fractions)), key=lambda i: -fractions[i])
        i = 0
        while delta != 0 and idx:
            j = idx[i % len(idx)]
            if delta > 0:
                counts[j] += 1; delta -= 1
            elif counts[j] > 0:
                counts[j] -= 1; delta += 1
            i += 1
            if i > 4 * len(fractions):
                break
    out = []
    for d, c in zip(dist, counts):
        out.append({**d, 'count': max(0, c)})
    return out


def _list_doc_ids(dataset: Dict[str, dict]) -> List[str]:
    return [k for k, v in dataset.items()
            if k != 'metadata' and isinstance(v, dict) and 'context' in v]


def build_blueprint(
    dataset: Dict[str, dict],
    num_questions: int,
    difficulty_distribution: Optional[List[Dict[str, Any]]] = None,
    patterns: Optional[List[str]] = None,
    seed: int = cfg.DETERMINISTIC_SEED,
    skill_instructions: str = '',
) -> List[Dict[str, Any]]:
    """Trả về list slot. Mỗi slot: {slot_id, doc_id, topic, cognitive_level,
    difficulty_target, question_pattern, skill}."""
    rng = random.Random(seed)
    doc_ids = _list_doc_ids(dataset)
    if not doc_ids or num_questions <= 0:
        return []

    # Round-robin doc_ids để mọi chunk đều được dùng (nếu num_questions >= len)
    rotated = list(doc_ids)
    rng.shuffle(rotated)
    doc_assignments: List[str] = []
    while len(doc_assignments) < num_questions:
        doc_assignments.extend(rotated)
    doc_assignments = doc_assignments[:num_questions]

    # Phân bố cognitive_level
    diff_dist = difficulty_distribution or cfg.DEFAULT_DIFFICULTY_DISTRIBUTION
    diff_pool: List[Dict[str, Any]] = []
    for d in _difficulty_split(num_questions, diff_dist):
        diff_pool.extend([{'cognitive_level': d['cognitive_level'],
                           'difficulty_target': d['difficulty_target']}] * d['count'])
    rng.shuffle(diff_pool)
    while len(diff_pool) < num_questions:
        diff_pool.append({'cognitive_level': 'Thông hiểu', 'difficulty_target': 0.5})

    # Pattern fallback (chỉ dùng khi LLM-inference không trả pattern_id)
    pattern_pool = patterns or cfg.QUESTION_PATTERNS
    pattern_count: Dict[str, int] = {}

    def fallback_pattern_for(topic: str, context: str = '') -> str:
        candidates = _patterns_matching_topic(pattern_pool, topic, context)
        avail = [p for p in candidates if pattern_count.get(p, 0) < PATTERN_REPEAT_LIMIT]
        if not avail:
            avail = candidates or [p['id'] if isinstance(p, dict) else p for p in pattern_pool]
        p = rng.choice(avail)
        pattern_count[p] = pattern_count.get(p, 0) + 1
        return p

    slots: List[Dict[str, Any]] = []
    for i in range(num_questions):
        doc_id = doc_assignments[i]
        diff = diff_pool[i]
        context = dataset[doc_id].get('context', '')
        topic = dataset[doc_id].get('topic', '')
        if not topic or topic.strip().lower() == 'chưa rõ chủ đề':
            inferred_topic = infer_topic_from_context(context)
            if inferred_topic and inferred_topic != 'Chưa rõ chủ đề':
                topic = inferred_topic

        # ---- LLM-driven inference (cached theo doc_id) ----
        # Khi không có API key, infer_for_chunk trả về structure rỗng → fallback.
        try:
            inferred = slot_inference.infer_for_chunk(
                doc_id, topic, context,
                skill_instructions=skill_instructions,
            )
        except Exception:
            inferred = {'meta_pattern': '', 'pattern_id': '', 'skill': '',
                        'misconceptions': []}

        pattern = inferred.get('pattern_id') or fallback_pattern_for(topic, context)
        meta_pattern = inferred.get('meta_pattern') or 'conceptual'
        skill = inferred.get('skill') or topic
        inferred_misconceptions = inferred.get('misconceptions') or []
        # Multi-slot từ cùng chunk: rotate misconception subset để đa dạng
        if len(inferred_misconceptions) > 5:
            offset = (i * 2) % len(inferred_misconceptions)
            inferred_misconceptions = (
                inferred_misconceptions[offset:] + inferred_misconceptions[:offset]
            )[:5]

        clean_context = dataset[doc_id].get('clean_context') if isinstance(dataset[doc_id].get('clean_context'), dict) else {}
        quality = clean_context.get('quality') if isinstance(clean_context.get('quality'), dict) else {}
        slot = {
            'slot_id': f'q_{i + 1:03d}',
            'doc_id': doc_id,
            'selected_chunk_ids': [doc_id],
            'selected_context_ids': [doc_id] if clean_context else [],
            'context_quality': quality,
            'risk_warning': _context_risk_warning(quality),
            'topic': topic,
            'cognitive_level': diff['cognitive_level'],
            'difficulty_target': diff['difficulty_target'],
            'question_pattern': pattern,
            'meta_pattern': meta_pattern,
            'skill': skill or f"{pattern} ({diff['cognitive_level']})",
            'inferred_misconceptions': inferred_misconceptions,
            'expected_question_type': 'single_choice',
            'requires_visual': False,
        }
        slots.append(slot)
    return slots


def _context_risk_warning(quality: Dict[str, Any]) -> str:
    if not quality:
        return ''
    if quality.get('is_usable') is False:
        return 'clean context is marked unusable'
    if quality.get('noise_level') == 'high':
        return 'clean context has high noise'
    try:
        value = float(quality.get('generation_value', 0.0))
    except (TypeError, ValueError):
        value = 0.0
    if value and value < 0.25:
        return 'clean context has low generation value'
    return ''


def summary(slots: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_level: Dict[str, int] = {}
    by_pattern: Dict[str, int] = {}
    by_doc: Dict[str, int] = {}
    for s in slots:
        by_level[s['cognitive_level']] = by_level.get(s['cognitive_level'], 0) + 1
        by_pattern[s['question_pattern']] = by_pattern.get(s['question_pattern'], 0) + 1
        by_doc[s['doc_id']] = by_doc.get(s['doc_id'], 0) + 1
    return {
        'total': len(slots),
        'by_cognitive_level': by_level,
        'by_pattern': by_pattern,
        'by_doc': by_doc,
    }
