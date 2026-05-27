"""Deterministic MCQ rule validation.

This module is the non-LLM formatting/schema gate used by Fast Mode before any
symbolic verifier or optional judge. It validates the candidate shape that the
generator emits and the final record shape that the formatter persists.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional


VALID_KEYS = {'A', 'B', 'C', 'D'}


def _norm(text: Any) -> str:
    s = str(text or '').strip().lower()
    s = s.replace('\u2212', '-').replace('\u00b7', '*')
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[.;:,\s]+$', '', s)
    return s


def _is_choice_label(text: Any) -> bool:
    return str(text or '').strip().upper().rstrip('.)') in VALID_KEYS


def _stem_contains_options(stem: str) -> bool:
    one_line = re.sub(r'\s+', ' ', stem or '')
    return re.search(r'\bA[.)]\s+.+\bB[.)]\s+.+\bC[.)]\s+.+\bD[.)]\s+', one_line) is not None


def candidate_options(candidate: Dict[str, Any]) -> List[str]:
    """Return answer + distractor texts in display order, if present."""
    answer = str(candidate.get('answer_text') or '').strip()
    distractors = candidate.get('distractors') or []
    texts = [answer]
    for d in distractors:
        if isinstance(d, dict):
            texts.append(str(d.get('distractor_text') or '').strip())
        else:
            texts.append(str(d or '').strip())
    return texts


def validate_candidate(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]] = None) -> List[str]:
    """Validate the generator candidate shape.

    Expected candidate fields:
      question_text, answer_text, answer_explanation_text, source_quote_text,
      distractors[3].distractor_text, verifier_hint.
    """
    issues: List[str] = []
    if not isinstance(candidate, dict):
        return ['candidate_not_object']

    stem = str(candidate.get('question_text') or '').strip()
    answer = str(candidate.get('answer_text') or '').strip()
    distractors = candidate.get('distractors') or []
    if not stem:
        issues.append('empty_stem')
    elif _stem_contains_options(stem):
        issues.append('stem_contains_embedded_options')
    elif len(stem) > 700:
        issues.append(f'stem_too_long:{len(stem)}')

    if not answer:
        issues.append('empty_answer')
    elif _is_choice_label(answer):
        issues.append('answer_is_choice_label')

    if len(distractors) != 3:
        issues.append(f'distractor_count={len(distractors)}')

    options = candidate_options(candidate)
    if len(options) != 4:
        issues.append(f'options_count={len(options)}')

    seen = set()
    for idx, text in enumerate(options, start=1):
        label = 'answer' if idx == 1 else f'd{idx - 1}'
        if not text:
            issues.append(f'{label}:empty')
            continue
        if _is_choice_label(text):
            issues.append(f'{label}:choice_label')
        if len(text) > 240:
            issues.append(f'{label}:too_long:{len(text)}')
        norm = _norm(text)
        if norm in seen:
            issues.append(f'{label}:duplicate_option')
        seen.add(norm)

    explanation = str(candidate.get('answer_explanation_text') or '').strip()
    if not explanation:
        issues.append('empty_explanation')
    elif len(explanation) > 1400:
        issues.append(f'explanation_too_long:{len(explanation)}')
    issues.extend(_trivial_stem_issues(candidate, slot))

    source_quote = str(candidate.get('source_quote_text') or '').strip()
    if not source_quote:
        issues.append('empty_source_quote')
    elif len(source_quote) > 350:
        issues.append(f'source_quote_too_long:{len(source_quote)}')

    hint = candidate.get('verifier_hint')
    if hint is not None and not isinstance(hint, dict):
        issues.append('verifier_hint_not_object')
    elif isinstance(hint, dict):
        payload = hint.get('payload')
        if payload is not None and not isinstance(payload, dict):
            issues.append('verifier_payload_not_object')
    if _needs_numeric_verifier(slot, candidate):
        hint_type = ''
        if isinstance(hint, dict):
            hint_type = str(hint.get('type') or 'none').strip().lower()
        if hint_type in {'', 'none'}:
            issues.append('verifier_missing:numeric_computation')

    issues.extend(_source_paraphrase_issues(candidate, slot))
    issues.extend(_source_quote_issues(candidate, slot))
    issues.extend(_distractor_rationale_issues(candidate))
    issues.extend(validate_solution_quality(candidate, slot))
    return issues


def validate_solution_quality(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]] = None) -> List[str]:
    """Fast Mode solution-depth gate; skipped for legacy writer candidates."""
    if not isinstance(candidate, dict):
        return []
    if not candidate.get('_fast_full_mcq') and 'detailed_solution' not in candidate:
        return []
    issues: List[str] = []
    detailed = candidate.get('detailed_solution')
    if not isinstance(detailed, dict):
        return ['explanation_low_quality:detailed_solution_missing']
    raw_steps = detailed.get('steps') or []
    if not isinstance(raw_steps, list):
        return ['explanation_low_quality:detailed_solution_steps_not_list']
    steps = [s for s in raw_steps if isinstance(s, dict) and str(s.get('content') or '').strip()]
    required = _required_solution_steps(slot)
    if len(steps) < required:
        issues.append(f'explanation_low_quality:solution_steps<{required}:{len(steps)}')
    if steps:
        first_title = _fold(str(steps[0].get('title') or ''))
        if 'ket luan' in first_title or 'conclusion' in first_title:
            issues.append('explanation_low_quality:first_step_is_conclusion')
    if _needs_math_work(slot, candidate):
        math_steps = sum(
            1 for step in steps
            if _has_math_signal(f"{step.get('title', '')} {step.get('content', '')}")
        )
        if math_steps == 0:
            issues.append('explanation_low_quality:no_formula_or_calculation_step')
    return issues


def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _required_solution_steps(slot: Optional[Dict[str, Any]]) -> int:
    level = _fold(str((slot or {}).get('cognitive_level') or ''))
    if 'van dung cao' in level or re.search(r'v.n d.ng cao', level):
        return 5
    if 'van dung' in level or re.search(r'v.n d.ng', level):
        return 4
    if 'thong hieu' in level or re.search(r'th.ng hi.u', level):
        return 3
    if 'nhan biet' in level or re.search(r'nh.n bi.t', level):
        return 2
    return 3


def _needs_math_work(slot: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> bool:
    slot = slot or {}
    pattern = _fold(str(slot.get('question_pattern') or slot.get('meta_pattern') or ''))
    verifier = candidate.get('verifier_hint') if isinstance(candidate.get('verifier_hint'), dict) else {}
    verifier_type = str(verifier.get('type') or slot.get('verifier_type') or 'none')
    return pattern in {'computation', 'application', 'reasoning'} or verifier_type not in {'', 'none'}


def _needs_numeric_verifier(slot: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> bool:
    slot = slot or {}
    pattern = _fold(str(slot.get('question_pattern') or slot.get('meta_pattern') or ''))
    if pattern not in {'computation', 'application'}:
        return False
    answer = str(candidate.get('answer_text') or '')
    if not re.search(r'\d|\\frac|dfrac|frac|sqrt|\\sqrt', answer):
        return False
    stem_fold = _fold(str(candidate.get('question_text') or ''))
    if any(word in stem_fold for word in (
        'tinh', 'bang bao nhieu', 'gia tri', 'quang duong',
        'dien tich', 'the tich', 'do doi', 'dien luong',
    )):
        return True
    return bool(re.search(r'^\s*(?:\\?d?frac|\(?-?\d)', answer))


def _has_math_signal(text: str) -> bool:
    return bool(re.search(
        r'(?:\d+\s*[+\-*/^=]\s*\d+|[=<>]|\\frac|\\sqrt|sqrt\(|∫|Σ|\^|C\s*\(|\bmod\b|\b\d+(?:[.,]\d+)?\b)',
        text or '',
        re.I,
    ))


def _trivial_stem_issues(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> List[str]:
    stem = str(candidate.get('question_text') or '')
    folded = _fold(stem)
    has_integral = bool(re.search(r'\\int|∫|tich phan', stem, re.I) or 'tich phan' in folded)
    if not has_integral:
        return []
    asks_direct_value = bool(re.search(r'\b(?:tinh|gia tri cua|bang bao nhieu)\b', folded))
    if not asks_direct_value:
        return []
    context_words = {
        'biet', 'cho ham', 'dien tich', 'hinh phang', 'luu luong', 'dien luong',
        'quang duong', 'van toc', 'the tich', 'nguyen ham', 'do thi',
    }
    if any(word in folded for word in context_words):
        return []
    if len(_content_token_list(stem)) <= 6:
        return ['question_too_trivial:bare_one_step_integral']
    return []


def _distractor_rationale_issues(candidate: Dict[str, Any]) -> List[str]:
    if not candidate.get('_fast_full_mcq'):
        return []
    issues: List[str] = []
    for idx, d in enumerate(candidate.get('distractors') or [], start=1):
        if not isinstance(d, dict):
            continue
        option = str(d.get('distractor_text') or '')
        reason = str(d.get('distractor_explanation_text') or '').strip()
        if not reason:
            issues.append(f'd{idx}:missing_distractor_rationale')
            continue
        option_is_numeric = bool(re.search(r'\d|\\frac|frac|dfrac', option))
        if not option_is_numeric:
            continue
        vague = bool(re.search(
            r'\b(?:tinh nham|cong nham|tru nham|sai dau|nham so|'
            r'sai do|thieu mot phan|calculation mistake)\b',
            _fold(reason),
        ))
        if vague and not _has_math_signal(reason):
            issues.append(f'd{idx}:vague_distractor_rationale')
    return issues


def _source_paraphrase_issues(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> List[str]:
    spans = (slot or {}).get('existing_question_spans') or []
    if not spans:
        return []
    stem = str(candidate.get('question_text') or '')
    stem_tokens = _content_tokens(stem)
    if len(stem_tokens) < 6:
        return []
    stem_numbers = set(re.findall(r'\d+(?:[.,]\d+)?', stem))
    for raw in spans[:6]:
        span = str(raw or '')
        span_tokens = _content_tokens(span)
        if len(span_tokens) < 6:
            continue
        overlap = len(stem_tokens & span_tokens) / max(1, len(stem_tokens | span_tokens))
        containment = len(stem_tokens & span_tokens) / max(1, len(stem_tokens))
        span_numbers = set(re.findall(r'\d+(?:[.,]\d+)?', span))
        same_numbers = bool(stem_numbers and stem_numbers <= span_numbers)
        common_run = _longest_common_token_run(stem_tokens, _content_token_list(span))
        if overlap >= 0.48 or (containment >= 0.70 and same_numbers) or common_run >= 9:
            return ['duplicate_question:source_exercise_paraphrase']
    return []

def _source_quote_issues(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> List[str]:
    quote = str(candidate.get('source_quote_text') or '').strip()
    if not quote:
        return []
    issues: List[str] = []
    if re.match(r'(?i)^\s*(topic|chunk type|context type|title)\s*:', quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    exercise_context = str((slot or {}).get('source_chunk_type') or '').lower() == 'exercise'
    if not exercise_context and not _quote_relevant_to_question(quote, candidate):
        issues.append('quote_mismatch:source_quote_not_relevant')
    if _looks_like_source_exercise(quote):
        issues.append('duplicate_question:source_quote_is_existing_exercise')
    return issues

def _looks_like_source_exercise(text: str) -> bool:
    folded = _fold(text)
    return bool(
        re.search(r'\b(?:cau|bai|question|exercise)\s*\d+[\.:)]?', folded)
        or re.search(
            r'\b(?:chon|dap an|phuong an|trac nghiem|hoi|bao nhieu|'
            r'khang dinh|dung sai)\b',
            folded,
        )
    )

def _quote_relevant_to_question(quote: str, candidate: Dict[str, Any]) -> bool:
    quote_tokens = _content_tokens(quote)
    if len(quote_tokens) < 3:
        return False
    qa_text = ' '.join([
        str(candidate.get('question_text') or ''),
        str(candidate.get('answer_text') or ''),
        str(candidate.get('answer_explanation_text') or ''),
    ])
    qa_tokens = _content_tokens(qa_text)
    if not qa_tokens:
        return False
    if _missing_required_concept_support(quote, qa_text):
        return False
    shared = quote_tokens & qa_tokens
    if len(shared) >= 2:
        return True
    # Formula-heavy quotes can be relevant even with few Vietnamese tokens.
    has_quote_math = bool(re.search(r'(?:\\int|∫|=|<=|>=|[<>]|\^|\d)', quote))
    has_qa_math = bool(re.search(r'(?:\\int|∫|=|<=|>=|[<>]|\^|\d)', qa_text))
    return has_quote_math and has_qa_math and len(shared) >= 1


def _has_integral_signal(text: str) -> bool:
    folded = _fold(text)
    return bool(
        'tich phan' in folded
        or re.search(r'(?:\\int|âˆ«||\uf0f2)', text)
    )


def _missing_required_concept_support(quote: str, qa_text: str) -> bool:
    """Reject generic quote overlap that misses the tested math concept."""
    q_fold = _fold(quote)
    qa_fold = _fold(qa_text)

    if _has_integral_signal(qa_text):
        quote_supports_integral = (
            _has_integral_signal(quote)
            or 'hinh phang gioi han' in q_fold
            or 'duoc tinh boi cong thuc' in q_fold
        )
        if not quote_supports_integral:
            return True

    return False


def _content_tokens(text: str) -> set[str]:
    return set(_content_token_list(text))

def _content_token_list(text: str) -> List[str]:
    folded = _fold(text)
    stop = {
        'cau', 'hoi', 'bai', 'cho', 'chon', 'dap', 'an', 'dung', 'sai',
        'mot', 'cac', 'trong', 'sau', 'la', 'co', 'voi', 'duoc', 'hay',
        'tinh', 'tim', 'phuong', 'ans', 'option', 'topic', 'chunk', 'type',
        'context', 'title', 'step', 'buoc', 'ket', 'luan',
    }
    return [
        t for t in re.findall(r'[a-z0-9]{3,}', folded)
        if t not in stop
    ]

def _longest_common_token_run(a_tokens: set[str], b_tokens: List[str]) -> int:
    if not a_tokens or not b_tokens:
        return 0
    longest = current = 0
    for token in b_tokens:
        if token in a_tokens:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def validate_record(record: Dict[str, Any]) -> List[str]:
    """Validate the final bank record after formatting/shuffle."""
    issues: List[str] = []
    if not isinstance(record, dict):
        return ['record_not_object']
    options = record.get('options') or []
    if len(options) != 4:
        issues.append(f'options_count={len(options)}')
    keys = [str(o.get('key') or '') for o in options if isinstance(o, dict)]
    if set(keys) != VALID_KEYS:
        issues.append('option_keys_invalid')
    answer_key = record.get('answer_key')
    if answer_key not in VALID_KEYS:
        issues.append('answer_key_invalid')
    if answer_key not in keys:
        issues.append('answer_key_missing')
    if not str(record.get('stem') or '').strip():
        issues.append('empty_stem')

    seen = set()
    for opt in options:
        if not isinstance(opt, dict):
            issues.append('option_not_object')
            continue
        key = opt.get('key') or '?'
        text = str(opt.get('text') or '').strip()
        if not text:
            issues.append(f'option_{key}_empty')
            continue
        if _is_choice_label(text):
            issues.append(f'option_{key}_choice_label')
        norm = _norm(text)
        if norm in seen:
            issues.append(f'option_{key}_duplicate_text')
        seen.add(norm)
    return issues


def first_issue_code(issues: Iterable[str]) -> str:
    items = list(issues)
    if not items:
        return ''
    joined = ' '.join(items)
    if 'source_exercise_paraphrase' in joined or 'duplicate_question' in joined:
        return 'duplicate_question'
    if 'explanation_low_quality' in joined or 'detailed_solution' in joined:
        return 'explanation_low_quality'
    if 'question_too_trivial' in joined:
        return 'quality_low'
    if 'verifier_missing' in joined:
        return 'verifier_failed'
    if 'distractor_rationale' in joined:
        return 'bad_distractors'
    if 'duplicate' in joined:
        return 'duplicate'
    if 'distractor_count' in joined or 'options_count' in joined:
        return 'bad_distractors'
    return 'format_error'
