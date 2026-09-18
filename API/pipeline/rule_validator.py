"""Deterministic MCQ rule validation.

This module is the non-LLM formatting/schema gate used by the prompt pipeline before any
symbolic verifier or optional judge. It validates the candidate shape that the
generator emits and the final record shape that the formatter persists.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from . import config as cfg


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


# Đề MCQ hợp lệ phải thật sự HỎI: có dấu ? hoặc từ khóa mệnh lệnh/nghi vấn.
# Bắt lớp lỗi "đề cụt" — writer sinh đủ dữ kiện nhưng thiếu câu hỏi cuối,
# học sinh không biết cần tính gì (đã gặp thực tế ở Direct_PDF).
_QUESTION_MARKERS = (
    '?', 'bao nhiêu', 'tính ', 'tìm ', 'hỏi ', 'hãy ', 'xác định',
    'là gì', 'bằng', 'chọn ', 'khẳng định nào', 'mệnh đề nào',
    'phương án nào', 'kết quả nào', 'giá trị nào', 'đáp án nào',
)


#: Dấu hiệu hỏi TỰ NÓ đủ mạnh, xuất hiện ở đâu cũng tính.
_STRONG_QUESTION_MARKERS = (
    '?', 'bao nhiêu', 'là gì', 'nào sau đây', 'khẳng định nào', 'mệnh đề nào',
    'phương án nào', 'kết quả nào', 'giá trị nào', 'đáp án nào', 'khi nào',
)

#: Động từ ra lệnh — CHỈ tính khi đứng đầu một mệnh đề (đầu đề, sau dấu câu),
#: nếu không thì "máy tính", "Chọn hệ trục toạ độ", "tìm được" đều khớp nhầm.
_IMPERATIVE_RE = re.compile(
    r'(?:^|[.;,:]\s+|\)\s+)(?:hãy\s+)?'
    r'(?:tính|tìm|xác định|cho biết|hỏi|nêu|viết)\b'
    # "tìm được", "tìm thấy" là thể hoàn thành trong câu kể, không phải mệnh lệnh.
    r'(?!\s*(?:được|thấy)\b)',
    re.IGNORECASE,
)

#: Kiểu đề "hoàn thành câu": kết thúc bằng "... bằng", "... là", "... bằng bao".
_COMPLETION_RE = re.compile(r'(?:bằng|là|có giá trị)\s*[.]?\s*$', re.IGNORECASE)


def _stem_asks_question(stem: str) -> bool:
    """Đề có thực sự hỏi gì không.

    Bản trước chỉ dò chuỗi con, nên "máy tính" khớp dấu hiệu 'tính ', "Chọn hệ
    trục toạ độ" khớp 'chọn ', và "bit bằng 0" khớp 'bằng'. Kết quả: đề chỉ mô
    tả dữ kiện rồi dừng vẫn được coi là có hỏi. Run 2026-07-25 có 5 câu như vậy
    lọt tới người dùng.
    """
    text = re.sub(r'\s+', ' ', str(stem or '')).strip()
    if not text:
        return False
    low = text.lower()
    if any(marker in low for marker in _STRONG_QUESTION_MARKERS):
        return True
    if _IMPERATIVE_RE.search(text):
        return True
    return bool(_COMPLETION_RE.search(text))


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
    elif not _stem_asks_question(stem):
        issues.append('stem_missing_question')

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
    issues.extend(_slot_topic_alignment_issues(candidate, slot))

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
    """Prompt-pipeline solution-depth gate; skipped for legacy writer candidates."""
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

def _slot_topic_alignment_issues(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> List[str]:
    slot = slot or {}
    topic_text = ' '.join([
        str(slot.get('topic') or ''),
        str(slot.get('skill') or ''),
        str(slot.get('question_pattern') or slot.get('meta_pattern') or ''),
    ])
    topic_fold = _fold(topic_text)
    if 'tich phan' not in topic_fold and '\\int' not in topic_text and '∫' not in topic_text:
        return []

    qa_text = ' '.join([
        str(candidate.get('question_text') or ''),
        str(candidate.get('answer_text') or ''),
        str(candidate.get('answer_explanation_text') or ''),
        str(candidate.get('source_quote_text') or ''),
    ])
    qa_fold = _fold(qa_text)
    if _has_integral_signal(qa_text):
        return []
    if _has_accumulation_signal(qa_fold):
        return []
    return ['slot_topic_mismatch:missing_integral_support']

def _has_accumulation_signal(folded_text: str) -> bool:
    return bool(
        any(term in folded_text for term in (
            'van toc', 'toc do', 'luu luong', 'dien luong', 'muc nuoc',
            'quang duong', 'dien tich hinh phang', 'hinh phang gioi han',
            'ham so lien tuc', 'nguyen ham', 'dao ham', 'bien thien theo thoi gian',
        ))
        and any(term in folded_text for term in (
            'ham so', 'f(x)', 'f(t)', 'v(t)', 'q(t)', "f'", "q'", "v'",
            'theo thoi gian', 'tren doan', 'doan [', 'cong thuc',
        ))
    )


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

def source_quote_issues(candidate: Dict[str, Any],
                        slot: Optional[Dict[str, Any]] = None) -> List[str]:
    """Các lỗi của riêng trích dẫn nguồn.

    Dùng khi cần thử nhiều trích dẫn ứng viên trước khi chốt (vd. writer chỉ
    sinh đề + lời giải, trích dẫn được dò lại trong tài liệu) — thay vì gọi
    ``validate_candidate`` vốn đòi candidate đã đủ phương án nhiễu.
    """
    return _source_quote_issues(candidate, slot)


def _source_quote_issues(candidate: Dict[str, Any], slot: Optional[Dict[str, Any]]) -> List[str]:
    quote = str(candidate.get('source_quote_text') or '').strip()
    if not quote:
        return []
    issues: List[str] = []
    if re.match(r'(?i)^\s*(topic|chunk type|context type|title|summary)\s*:', quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif re.search(r'(?i)\b(chunk type|use note|anti-copy note|questionable skills)\s*:', quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif 'picture text' in _fold(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif 'he thong bai tap' in _fold(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif _quote_is_generic_heading(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    qa_text = ' '.join([
        str(candidate.get('question_text') or ''),
        str(candidate.get('answer_text') or ''),
        str(candidate.get('answer_explanation_text') or ''),
    ])
    if _missing_required_concept_support(quote, qa_text):
        issues.append('quote_mismatch:source_quote_not_relevant')
    exercise_context = str((slot or {}).get('source_chunk_type') or '').lower() == 'exercise'
    if not exercise_context and not _quote_relevant_to_question(quote, candidate):
        issues.append('quote_mismatch:source_quote_not_relevant')
    if _looks_like_source_exercise(quote):
        issues.append('duplicate_question:source_quote_is_existing_exercise')
    return issues

def _quote_is_generic_heading(quote: str) -> bool:
    folded = _fold(quote)
    if 'formula-not-decoded' in folded:
        return True
    has_supporting_math = bool(re.search(
        r'(?:\\int|∫|=|\\frac|frac|\\ln|ln\s*\||cos|sin|e\^|x\^|\d|c\s+la\s+hang\s+so)',
        quote,
        re.I,
    ))
    heading_hits = sum(
        1 for term in (
            'chuyen de', 'bai', 'nguyen ham tich phan',
            'nguyen ham cua mot so ham so', 'tinh chat co ban',
            'khai niem tich phan',
        )
        if term in folded
    )
    if heading_hits and not has_supporting_math and len(_content_token_list(quote)) <= 8:
        return True
    if heading_hits < 2:
        return False
    return not has_supporting_math

def _looks_like_source_exercise(text: str) -> bool:
    folded = _fold(text)
    return bool(
        re.search(r'\b(?:cau|bai|question|exercise)\s*\d+[\.:)]?', folded)
        or re.search(
            r'\b(?:chon|dap an|phuong an|trac nghiem|hoi|bao nhieu|'
            r'khang dinh|dung sai|loi giai|context|page)\b',
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
    """Reject generic quote overlap that misses the tested math concept.

    Legacy (strict) behavior: hard-reject whenever the quote does not literally
    contain the exact formula family / concrete numbers used in the question.
    This is far too aggressive on theory-only chunks, where a legitimate
    computational question is written from a general rule the quote states.

    Lenient (default): this brittle gate is disabled and topical relevance is
    instead enforced by token overlap in `_quote_relevant_to_question`.
    Set AQG_QUOTE_RELEVANCE_STRICT=1 to restore the legacy gate.
    """
    if not cfg.QUOTE_RELEVANCE_STRICT:
        return False

    q_fold = _fold(quote)
    qa_fold = _fold(qa_text)

    required_family = _required_formula_family(qa_text)
    if required_family and not _quote_supports_formula_family(quote, required_family):
        return True
    if _specific_math_needs_quote_support(quote, qa_text):
        return True

    if _has_integral_signal(qa_text):
        quote_supports_integral = (
            _has_integral_signal(quote)
            or 'hinh phang gioi han' in q_fold
            or 'duoc tinh boi cong thuc' in q_fold
        )
        if not quote_supports_integral:
            return True

    return False

def _specific_math_needs_quote_support(quote: str, qa_text: str) -> bool:
    """Reject invented concrete examples when the quote is only a broad rule/heading."""
    raw_q = str(quote or '')
    raw_qa = str(qa_text or '')
    q_fold = _fold(raw_q)
    qa_fold = _fold(raw_qa)
    q_compact = re.sub(r'\s+', '', q_fold)
    qa_compact = re.sub(r'\s+', '', qa_fold)

    domain_groups = [
        ('motion', ('gia toc', 'van toc', 'quang duong', 'chuyen dong', 'vi tri')),
        ('population', ('dan so', 'tang truong', 'mo hinh dan so')),
        ('area', ('dien tich', 'hinh phang', 'duong cong', 'do thi')),
    ]
    for _, terms in domain_groups:
        if any(term in qa_fold for term in terms) and not any(term in q_fold for term in terms):
            return True

    qa_numbers = set(re.findall(r'(?<![a-zA-Z])-?\d+(?:[.,]\d+)?', raw_qa))
    qa_numbers = {n.replace(',', '.') for n in qa_numbers if n.replace(',', '.') not in {'0', '1'}}
    if qa_numbers:
        quote_numbers = {n.replace(',', '.') for n in re.findall(r'(?<![a-zA-Z])-?\d+(?:[.,]\d+)?', raw_q)}
        quote_supports_linearity = (
            any(term in q_fold for term in ('tong', 'hieu', 'tuyen tinh'))
            and any(term in qa_compact for term in ('f(x)', 'g(x)', 'fx', 'gx'))
        )
        if not quote_supports_linearity and not qa_numbers & quote_numbers:
            return True

    formula_heads = re.findall(
        r'([A-Za-z]\s*\([^)]*\)\s*=\s*[^,.;\s]+)',
        raw_qa,
    )
    if formula_heads:
        compact_quote = re.sub(r'\s+', '', raw_q).lower()
        for formula in formula_heads[:3]:
            if re.sub(r'\s+', '', formula).lower() in compact_quote:
                return False
        if '=' not in raw_q and not any(ch in q_compact for ch in ('dao', 'nguyenham')):
            return True

    if 'f(x)<=0' in qa_compact or 'f(x)\u22640' in qa_compact or 'khongduong' in qa_compact:
        return not any(term in q_compact for term in ('f(x)<=0', 'f(x)\u22640', 'khongduong', 'am', 'duoitruchoanh'))

    return False

def _required_formula_family(qa_text: str) -> str:
    raw = str(qa_text or '')
    folded = _fold(raw)
    compact = re.sub(r'\s+', '', folded)
    if re.search(r'x\s*\^\s*\{?\s*n\s*\}?|x\^n|x\s+m[uũ]?', folded, re.I):
        return 'power_xn'
    if re.search(r'(?:\\frac\s*\{?1\}?\s*\{?x\}?|1\s*/\s*x)', raw) or 'ln|x|' in compact:
        return 'reciprocal_x'
    if re.search(r'e\s*\^\s*\{?\s*x\s*\}?|e\^x', raw, re.I) or 'e^x' in compact:
        return 'exp_ex'
    if 'cos' in folded:
        return 'trig_cos'
    if 'sin' in folded:
        return 'trig_sin'
    if 'f(x)+c' in compact or ('vai tro' in folded and re.search(r'\bc\b', folded)):
        return 'constant_c'
    if 'can duoi' in folded or re.search(r'\\int\s*_\s*\{?a\}?\s*\^\s*\{?b\}?', raw):
        return 'integral_bounds'
    return ''

def _quote_supports_formula_family(quote: str, family: str) -> bool:
    raw = str(quote or '')
    folded = _fold(raw)
    compact = re.sub(r'\s+', '', folded)
    if family == 'power_xn':
        return bool(re.search(r'x\s*\^\s*\{?\s*n\s*\}?|x\^n|luy\s+thua', folded, re.I))
    if family == 'reciprocal_x':
        return bool(re.search(r'(?:\\frac\s*\{?1\}?\s*\{?x\}?|1\s*/\s*x|ln\s*\|?x)', raw, re.I)) or 'ln|x|' in compact
    if family == 'exp_ex':
        return bool(re.search(r'e\s*\^\s*\{?\s*x\s*\}?|e\^x', raw, re.I)) or 'ham so mu' in folded
    if family == 'trig_cos':
        return 'cos' in folded
    if family == 'trig_sin':
        return 'sin' in folded
    if family == 'constant_c':
        return bool(re.search(r'\bc\b', folded)) and ('hang so' in folded or 'hangso' in compact)
    if family == 'integral_bounds':
        return (
            'can duoi' in folded
            or 'canduoi' in compact
            or bool(re.search(r'\\int\s*_\s*\{?a\}?\s*\^\s*\{?b\}?|∫\s*a\s*b', raw, re.I))
        )
    return True


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

    source = record.get('source') if isinstance(record.get('source'), dict) else {}
    quote = str(source.get('quote') or '').strip()
    if not quote:
        issues.append('empty_source_quote')
    elif len(quote) > 350:
        issues.append(f'source_quote_too_long:{len(quote)}')
    elif re.match(r'(?i)^\s*(topic|chunk type|context type|title|summary)\s*:', quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif re.search(r'(?i)\b(chunk type|use note|anti-copy note|questionable skills)\s*:', quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif 'picture text' in _fold(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif 'he thong bai tap' in _fold(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif _quote_is_generic_heading(quote):
        issues.append('quote_mismatch:source_quote_is_metadata')
    elif _looks_like_source_exercise(quote):
        issues.append('duplicate_question:source_quote_is_existing_exercise')
    else:
        answer_text = ''
        for opt in options:
            if isinstance(opt, dict) and opt.get('key') == answer_key:
                answer_text = str(opt.get('text') or '')
                break
        qa_text = ' '.join([
            str(record.get('stem') or ''),
            answer_text,
            str(record.get('explanation_correct') or ''),
            str(record.get('short_explanation') or ''),
        ])
        if _missing_required_concept_support(quote, qa_text):
            issues.append('quote_mismatch:source_quote_not_relevant')

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
