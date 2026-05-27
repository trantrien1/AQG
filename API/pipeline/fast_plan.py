"""Deterministic internal planning for Fast Mode.

Fast Mode intentionally avoids the LLM planner. It creates compact slots from
clean_contexts and leaves plan review to Advanced Mode.
"""
from __future__ import annotations

import random
import re
import unicodedata
from typing import Any, Dict, List, Optional

from . import config as cfg


def _chunks(dataset: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    items: List[tuple[str, Dict[str, Any]]] = []
    seen_signatures: set[str] = set()
    for doc_id, doc in dataset.items():
        if doc_id == 'metadata' or not isinstance(doc, dict) or 'context' not in doc:
            continue
        clean = doc.get('clean_context') if isinstance(doc.get('clean_context'), dict) else {}
        quality = clean.get('quality') if isinstance(clean.get('quality'), dict) else {}
        if quality.get('is_usable') is False or quality.get('noise_level') == 'high':
            continue
        if _runtime_context_unusable(doc):
            continue
        signature = _context_signature(doc)
        if signature and signature in seen_signatures:
            continue
        if signature:
            seen_signatures.add(signature)
        items.append((doc_id, doc))
    if items:
        return items
    return [
        (doc_id, doc)
        for doc_id, doc in dataset.items()
        if doc_id != 'metadata' and isinstance(doc, dict) and 'context' in doc
    ]


def _difficulty_pool(total: int, distribution: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    dist = distribution or cfg.DEFAULT_DIFFICULTY_DISTRIBUTION
    fractions = [float(d.get('fraction', 0) or 0) for d in dist]
    denom = sum(fractions) or 1.0
    counts = [int(round(total * f / denom)) for f in fractions]
    while sum(counts) < total and counts:
        counts[fractions.index(max(fractions))] += 1
    while sum(counts) > total and counts:
        idx = max(range(len(counts)), key=lambda i: counts[i])
        counts[idx] -= 1

    pool: List[Dict[str, Any]] = []
    for raw, count in zip(dist, counts):
        pool.extend([{
            'cognitive_level': raw.get('cognitive_level', 'Thông hiểu'),
            'difficulty_target': raw.get('difficulty_target', 0.5),
        }] * max(0, count))
    while len(pool) < total:
        pool.append({'cognitive_level': 'Thông hiểu', 'difficulty_target': 0.5})
    return pool[:total]


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return doc.get('clean_context') if isinstance(doc.get('clean_context'), dict) else {}


def _chunk_type(doc: Dict[str, Any]) -> str:
    return str(_clean(doc).get('chunk_type') or 'theory')


def _generation_value(doc: Dict[str, Any]) -> float:
    quality = _clean(doc).get('quality') if isinstance(_clean(doc).get('quality'), dict) else {}
    try:
        return float(quality.get('generation_value') or 0.0)
    except (TypeError, ValueError):
        return 0.0

def _clean_topic_value(*values: Any) -> str:
    """Return a display-safe topic, avoiding OCR fragments like `2 2 (m/s).`."""
    unit_tokens = {'m', 's', 'ms', 'm/s', 'lit', 'l', 'cm', 'kg'}
    for value in values:
        topic = re.sub(r'\s+', ' ', str(value or '')).strip()
        if not topic:
            continue
        folded = _fold(topic)
        if any(key in folded for key in (
            'nguyen ham', 'tich phan', 'dien tich', 'do thi', 'toan',
            'van toc', 'quang duong', 'luu luong', 'dien luong',
        )):
            return topic
        words = [
            w for w in re.findall(r'[a-zA-ZÀ-ỹĐđ/]{2,}', topic)
            if _fold(w) not in unit_tokens
        ]
        if len(words) >= 2:
            return topic
    return 'Toán'


def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _context_text(doc: Dict[str, Any]) -> str:
    clean = _clean(doc)
    parts: List[str] = []
    for key in ('clean_text', 'key_definitions', 'key_formulas', 'key_theorems', 'worked_examples'):
        val = clean.get(key)
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
        elif val:
            parts.append(str(val))
    if not parts:
        parts.append(str(doc.get('context') or ''))
    return '\n'.join(parts)

def _looks_university_level_math(folded: str) -> bool:
    """Filter topics outside the intended Vietnamese high-school AQG scope."""
    advanced_terms = (
        'tich phan duong', 'line integral', 'green theorem', 'dinh ly green',
        'chuoi fourier', 'fourier', 'jacobian', 'ma tran jacobi', 'gradient',
        'divergence', 'curl', 'tham so hoa duong cong', 'duong cong tham so',
    )
    if any(term in folded for term in advanced_terms):
        return True
    parametric_area = any(re.search(pattern, folded) for pattern in (
        r"x\s*\(\s*t\s*\).*y\s*'\s*\(\s*t\s*\)",
        r"x\s*y\s*'\s*-\s*y\s*x\s*'",
        r"x\s*=\s*[^\n]*(?:cos|sin)\s*t[^\n]*y\s*=\s*[^\n]*(?:sin|cos)\s*t",
    ))
    if parametric_area and any(term in folded for term in ('elip', 'dien tich', 'hinh quat')):
        return True
    if 'tham so hoa' in folded and any(term in folded for term in ('elip', 'duong cong', 'hinh quat')):
        return True
    if any(term in folded for term in ('elip', 'e-lip', 'e lip')) and any(term in folded for term in ('hinh quat', 'dien tich')):
        return True
    return False

def _runtime_context_unusable(doc: Dict[str, Any]) -> bool:
    """Catch stale clean_context quality that predates stronger OCR guards."""
    text = _context_text(doc)
    if not text.strip():
        return True
    private_use = sum(1 for ch in text if unicodedata.category(ch) == 'Co')
    private_ratio = private_use / max(1, len(text))
    alpha = sum(1 for ch in text if ch.isalpha())
    if private_ratio > 0.05:
        return True
    if private_ratio > 0.02 and alpha < 80:
        return True
    folded = _fold(text)
    if _looks_university_level_math(folded):
        return True
    math_signal = bool(
        re.search(r'\\int|∫|=|[<>]|\d|cos|sin|parabol|elip|do thi|dien tich|'
                  r'nguyen ham|tich phan|van toc|luu luong|dien luong|quang duong',
                  folded)
    )
    if len(folded) < 80 and not math_signal:
        return True
    weak_only = folded.strip() in {
        'nhan dien dinh nghia/cong thuc',
        'he thong bai tap toan thuc te.',
    }
    if weak_only:
        return True
    return False

def _context_signature(doc: Dict[str, Any]) -> str:
    text = _fold(_context_text(doc))
    tokens = [
        t for t in re.findall(r'[a-z0-9]{3,}', text)
        if t not in {'summary', 'context', 'topic', 'chunk', 'type'}
    ]
    if len(tokens) < 8:
        return ''
    return ' '.join(tokens[:80])

def _type_rank(doc: Dict[str, Any]) -> int:
    ctype = _chunk_type(doc)
    if ctype == 'theory':
        return 0
    if ctype == 'example':
        return 1
    return 2


def _question_type(text: str, level: str) -> str:
    low = text.lower()
    has_formula = bool(re.search(r'=|\\frac|\\sqrt|\^|\bmod\b|\bC\s*\(|\bn!\b|\d', text))
    if any(x in low for x in ('ví dụ', 'bài toán', 'lời giải', 'example', 'exercise')):
        return 'application' if 'Vận dụng' in level else 'computation'
    if has_formula and level not in {'Nhận biết', 'Thông hiểu'}:
        return 'computation'
    if any(x in low for x in ('chứng minh', 'suy ra', 'vì sao', 'mệnh đề')):
        return 'reasoning'
    return 'conceptual'


def _question_type_for_doc(doc: Dict[str, Any], level: str) -> str:
    ctype = _chunk_type(doc)
    text = _context_text(doc)
    folded_level = _fold(level)
    has_formula = bool(re.search(r'=|\\frac|\\sqrt|\^|\bmod\b|\bC\s*\(|\bn!\b|\d', text))
    if ctype == 'theory':
        if 'nhan biet' in folded_level or 'thong hieu' in folded_level:
            return 'conceptual'
        if has_formula:
            return 'computation'
    if ctype == 'example':
        return 'application' if 'van dung' in folded_level else 'computation'
    if ctype == 'exercise':
        if 'van dung' in folded_level:
            return 'application'
        if has_formula:
            return 'computation'
    return _question_type(text, level)


def _verifier_type(text: str, qtype: str) -> str:
    low = text.lower()
    has_machine_check_signal = bool(re.search(r'\d|=|\\frac|\\sqrt|\^|\bmod\b|\bC\s*\(|\bn!\b', text))
    if qtype == 'conceptual':
        return 'none'
    if re.search(r'\bmod\b|modulo|đồng dư', low):
        return 'modular'
    if re.search(r'\bC\s*\(|binomial|factorial|tổ hợp|chỉnh hợp|hoán vị|n!', text, re.I):
        return 'counting'
    if 'ma trận' in low or 'matrix' in low:
        return 'matrix_det'
    if 'đồ thị' in low or 'graph' in low:
        return 'graph_property'
    if 'giới hạn' in low or 'limit' in low:
        return 'limit'
    if 'đạo hàm' in low or 'derivative' in low:
        return 'derivative'
    if 'tích phân' in low or 'integral' in low:
        return 'integral'
    if re.search(r'\d|=', text):
        return 'numeric_eval'
    return 'none'


def _skill(doc: Dict[str, Any], qtype: str) -> str:
    clean = _clean(doc)
    topic = _clean_topic_value(clean.get('topic'), doc.get('topic'), clean.get('title'))
    for key in ('key_formulas', 'key_theorems', 'key_definitions'):
        items = clean.get(key)
        if isinstance(items, list) and items:
            item = re.sub(r'\s+', ' ', str(items[0])).strip()
            return item[:140] if item else str(topic)
    return f'{topic}: {qtype}'


def _misconceptions(qtype: str) -> List[Dict[str, str]]:
    if qtype == 'computation':
        return [
            {'id': 'calc_step_error', 'wrong_form': 'sai một bước tính', 'rationale': 'nhầm công thức hoặc số học'},
            {'id': 'wrong_formula', 'wrong_form': 'dùng công thức gần đúng nhưng sai', 'rationale': 'không bám điều kiện'},
        ]
    if qtype == 'reasoning':
        return [
            {'id': 'reverse_implication', 'wrong_form': 'đảo chiều suy luận', 'rationale': 'nhầm điều kiện cần/đủ'},
            {'id': 'missing_condition', 'wrong_form': 'bỏ qua giả thiết', 'rationale': 'kết luận thiếu điều kiện'},
        ]
    return [
        {'id': 'concept_confusion', 'wrong_form': 'nhầm khái niệm gần nghĩa', 'rationale': 'đọc sai định nghĩa'},
        {'id': 'overgeneralization', 'wrong_form': 'khái quát hóa quá mức', 'rationale': 'áp dụng ngoài phạm vi'},
    ]


def build_fast_plan(
    dataset: Dict[str, Any],
    num_questions: int,
    *,
    seed: int = cfg.DETERMINISTIC_SEED,
    difficulty_distribution: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    docs = _chunks(dataset)
    if not docs or num_questions <= 0:
        return []

    rng = random.Random(seed)
    ranked = sorted(
        docs,
        key=lambda item: (
            _type_rank(item[1]),
            -_generation_value(item[1]),
            rng.random(),
        ),
    )
    assignments: List[tuple[str, Dict[str, Any]]] = []
    while len(assignments) < num_questions:
        assignments.extend(ranked)
    assignments = assignments[:num_questions]

    diff_pool = _difficulty_pool(num_questions, difficulty_distribution)
    slots: List[Dict[str, Any]] = []
    for i, ((doc_id, doc), diff) in enumerate(zip(assignments, diff_pool), start=1):
        clean = _clean(doc)
        text = _context_text(doc)
        qtype = _question_type_for_doc(doc, diff['cognitive_level'])
        cognitive_level = diff['cognitive_level']
        difficulty_target = diff['difficulty_target']
        if qtype in {'computation', 'application'}:
            folded_level = _fold(cognitive_level)
            if 'nhan biet' in folded_level or 'thong hieu' in folded_level:
                cognitive_level = 'Vận dụng'
                difficulty_target = max(float(difficulty_target or 0.0), 0.65)
        verifier_type = _verifier_type(text, qtype)
        topic = _clean_topic_value(clean.get('topic'), doc.get('topic'), clean.get('title'))
        quality = clean.get('quality') if isinstance(clean.get('quality'), dict) else {}
        chunk_type = _chunk_type(doc)
        slots.append({
            'slot_id': f'q_{i:03d}',
            'doc_id': doc_id,
            'topic': topic,
            'skill': _skill(doc, qtype),
            'cognitive_level': cognitive_level,
            'difficulty_target': difficulty_target,
            'question_pattern': qtype,
            'meta_pattern': qtype,
            'question_type': 'single_choice',
            'expected_question_type': 'single_choice',
            'selected_chunk_ids': [doc_id],
            'selected_context_ids': [doc_id],
            'verifier_type': verifier_type,
            'context_quality': quality,
            'source_chunk_type': chunk_type,
            'existing_question_spans': clean.get('existing_question_spans') or [],
            'risk_warning': (
                'source chunk is exercise; generator must create a new item, not paraphrase'
                if chunk_type == 'exercise' else ''
            ),
            'inferred_misconceptions': _misconceptions(qtype),
            'requires_visual': False,
        })
    return slots
