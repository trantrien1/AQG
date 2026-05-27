"""Item-Writing Flaws (IWF) checker — rule-based, không tốn LLM.

Gom các quy tắc viết MCQ kinh điển (NBME-style) chưa được phủ bởi
`filter._check_*`. Mỗi check trả về True nếu candidate PASS.

Wire-in: gọi từ `filter.validate_distractors`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


# Cụm từ tuyệt đối trong distractor là red-flag (học sinh học mẹo loại trừ).
_ABSOLUTE_TERMS = [
    'luôn luôn', 'luôn', 'mọi trường hợp', 'tất cả các trường hợp',
    'không bao giờ', 'tuyệt đối không', 'chắc chắn không',
    'always', 'never', 'absolutely', 'definitely',
]


def _check_no_absolute_terms(response: Dict[str, Any]) -> bool:
    """Distractor không nên chứa cụm tuyệt đối — học sinh dễ loại bằng mẹo.

    (Cho phép trong đáp án đúng hoặc trong stem nếu bám sát ngữ cảnh.)
    """
    for d in response.get('distractors', []):
        t = (d.get('distractor_text', '') or '').lower()
        if any(term in t for term in _ABSOLUTE_TERMS):
            return False
    return True


_NUMERIC_RE = re.compile(r'^\s*-?\d+(?:[.,]\d+)?\s*$')

# Các "non-numeric value" hợp lệ trong toán mà không nên bị reject khi
# trộn với option thuần số: vô cùng, không tồn tại, không xác định.
_MATH_VALUE_TOKENS_RE = re.compile(
    r'^(?:[+−\-]?\s*(?:∞|inf|infty)|không\s+(?:tồn\s+tại|xác\s+định)|undefined|DNE)$',
    re.IGNORECASE,
)


def _is_pure_numeric(text: str) -> bool:
    return bool(_NUMERIC_RE.match(text or ''))


def _is_math_value(text: str) -> bool:
    """True nếu text là số thuần hoặc giá trị toán đặc biệt (∞, không tồn tại)."""
    t = (text or '').strip()
    return _is_pure_numeric(t) or bool(_MATH_VALUE_TOKENS_RE.match(t))


def _check_format_consistency(response: Dict[str, Any]) -> bool:
    """Tránh trộn giá trị-thuần với cụm-chữ-mô-tả.

    Cho phép trộn số với ∞ / "không tồn tại" / "không xác định" (đều là math
    values). Chỉ fail khi đáp án là số nhưng có distractor là MỘT CÂU MÔ TẢ
    (>= 12 ký tự không thuộc dạng math value).
    """
    options = [response.get('answer_text', '')] + [
        d.get('distractor_text', '') for d in response.get('distractors', [])
    ]
    if len(options) < 4:
        return True
    if not all(_is_math_value(o) or _is_pure_numeric(o) for o in [options[0]]):
        # Đáp án không phải số/giá-trị-toán → không áp rule này
        if not _is_pure_numeric(options[0]):
            return True
    # Đáp án là số → mọi option phải là math value HOẶC text ngắn (< 12 ký tự)
    for o in options:
        if _is_math_value(o):
            continue
        if len((o or '').strip()) < 12:
            continue
        return False
    return True


def _to_float(text: str):
    try:
        return float((text or '').replace(',', '.').strip())
    except (ValueError, AttributeError):
        return None


def _check_numeric_scale_balance(response: Dict[str, Any]) -> bool:
    """Khi đáp án và distractor đều là số, không có distractor nào có
    magnitude khác biệt hơn 1000× so với median — distractor lệch quá lớn
    là không hợp lý (học sinh đoán dễ).
    """
    options = [response.get('answer_text', '')] + [
        d.get('distractor_text', '') for d in response.get('distractors', [])
    ]
    nums = [_to_float(o) for o in options]
    if not all(n is not None for n in nums):
        return True  # không phải bài toán số thuần → bỏ qua check
    abs_nums = [abs(n) for n in nums if n != 0]
    if len(abs_nums) < 2:
        return True
    abs_nums.sort()
    median = abs_nums[len(abs_nums) // 2]
    if median == 0:
        return True
    for n in abs_nums:
        ratio = n / median if n >= median else median / n
        if ratio > 1000:
            return False
    return True


def _check_distractor_min_length(response: Dict[str, Any]) -> bool:
    """Distractor không quá ngắn (< 1 ký tự không-trống) — tránh placeholder.

    Loại các trường hợp 'A', '?', '...'.
    """
    for d in response.get('distractors', []):
        t = (d.get('distractor_text', '') or '').strip()
        if len(t) < 1:
            return False
        # Phải có ít nhất một ký tự alphanumeric
        if not re.search(r'[0-9A-Za-zÀ-ỹĐđ]', t):
            return False
    return True


def _check_no_duplicate_distractor(response: Dict[str, Any]) -> bool:
    """Hai distractor không được trùng nhau (sau normalize whitespace + lower)."""
    texts = [
        re.sub(r'\s+', ' ', (d.get('distractor_text', '') or '').strip().lower())
        for d in response.get('distractors', [])
    ]
    texts = [t for t in texts if t]
    return len(texts) == len(set(texts))


def _check_misconception_category_diversity(response: Dict[str, Any]) -> bool:
    """When categories are present, require one misconception per distractor."""
    cats = [
        (d.get('distractor_category_text') or '').strip().lower()
        for d in response.get('distractors', [])
    ]
    cats = [c for c in cats if c and c not in ('null', 'none', 'n/a', '-')]
    if len(cats) < 2:
        return True
    return len(cats) == len(set(cats))


_IWF_CHECKS = {
    'iwf_no_absolute_terms':    _check_no_absolute_terms,
    'iwf_format_consistency':   _check_format_consistency,
    'iwf_numeric_scale':        _check_numeric_scale_balance,
    'iwf_distractor_min_length': _check_distractor_min_length,
    'iwf_no_duplicate_distractor': _check_no_duplicate_distractor,
    'iwf_misconception_category_diversity': _check_misconception_category_diversity,
}


def run_iwf_checks(response: Dict[str, Any]) -> Dict[str, bool]:
    """Trả dict {check_name: passed}. Caller tự AND/OR theo policy."""
    return {name: fn(response) for name, fn in _IWF_CHECKS.items()}


def failed_iwf_checks(response: Dict[str, Any]) -> List[str]:
    return [name for name, ok in run_iwf_checks(response).items() if not ok]
