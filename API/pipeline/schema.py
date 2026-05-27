"""Output schema (mục 18): chuyển candidate đã pass filter → câu hỏi định dạng cuối."""
from __future__ import annotations

import datetime as dt
import random
import re
import uuid
from typing import Any, Dict, List

from . import difficulty as diff_mod
from .parsing import _sympy_to_natural


# ==== Output Cleaner ====
# LLM đôi khi rò rỉ marker nội bộ ("Answer explanation:", "Reasoning:", v.v.)
# vào text hiển thị (stem/option). Cleaner cắt từ marker đó về sau để giữ
# output sạch như MCQ thật.
_LEAK_MARKER_PATTERN = re.compile(
    r'\s*(?:Answer\s+explanation|Answer\s*key|Answer|Source\s+quote|'
    r'Verifier\s+hint|Distractor\s+category|Distractor\s+explanation|'
    r'Distractor\s+text|Distractor|Reasoning|Correct\s+answer|'
    r'Visual\s+spec|Visual|Explanation|Rationale|Question)\s*[:：]',
    re.IGNORECASE,
)

# Derivation markers — khi option chứa các bước suy luận, lấy KẾT LUẬN cuối cùng
# (phần sau marker cuối). Tránh `→` vì hay xuất hiện trong notation lim_{x→0}.
_DERIVATION_MARKERS = re.compile(
    # `→` chỉ match khi có space cả 2 bên (tránh `lim_{x→0}`)
    r'(?:\s+→\s+|\s*(?:⇒|=>|\\Rightarrow)\s*|'
    r'\s*(?:\bdo\s+đó\b|\bsuy\s+ra\b|\btừ\s+đó\b|\btheo\s+đó\b|\bdo\s+vậy\b)\s*)',
    re.IGNORECASE,
)


def _clean_display_text(text: str, max_len: int = 280) -> str:
    """Strip LLM-internal markers + trailing junk khỏi text hiển thị.

    - Cắt mọi marker dạng "Answer explanation:", "Reasoning:", etc.
    - Loại bỏ trailing whitespace/punctuation thừa.
    - Cap độ dài tối đa (cắt câu hợp lý nếu quá dài).
    """
    if not text:
        return text
    s = str(text)

    # 1. Cắt từ marker đầu tiên về sau
    m = _LEAK_MARKER_PATTERN.search(s)
    if m:
        if m.start() > 0:
            s = s[:m.start()].rstrip()
        else:
            # Marker ở đầu → strip header line, recurse phần còn lại
            s = s[m.end():].lstrip(' :\t-')
            return _clean_display_text(s, max_len)

    # 2. Loại bỏ ký tự markdown/code thừa
    s = s.strip().strip('"“”')
    # Trailing comma/colon (do cắt ngang)
    s = re.sub(r'[,;:]\s*$', '', s)
    s = re.sub(r'\s+', ' ', s)
    s = _sympy_to_natural(s)

    # 3. Cap length: nếu quá dài, cắt ở câu/dấu cuối hợp lý
    if len(s) > max_len:
        # Tìm dấu kết thúc câu gần max_len
        cut = s.rfind('.', 0, max_len)
        if cut < max_len * 0.6:
            cut = s.rfind(';', 0, max_len)
        if cut < max_len * 0.6:
            cut = s.rfind(',', 0, max_len)
        if cut < max_len * 0.5:
            cut = max_len
        s = s[:cut + 1].rstrip()

    return s.strip()


def _clean_option_text(text: str) -> str:
    """Cleaner cho phương án A/B/C/D: ngắn (≤ 120 chars), chỉ chứa kết luận.

    - Strip LLM markers (Answer:, Reasoning:, ...)
    - Nếu chứa bước suy luận (⇒, do đó, suy ra...) → giữ phần SAU marker cuối cùng
      (đó là kết quả cuối, không phải đạo hàm các bước).
    - Strip leading explanatory connector ("Từ", "Vì", "Do" ở đầu).
    - Cap 120 chars.
    """
    if not text:
        return text
    s = _clean_display_text(str(text), max_len=200)

    # Nếu có nhiều marker derivation → giữ phần sau marker cuối
    matches = list(_DERIVATION_MARKERS.finditer(s))
    if matches:
        last = matches[-1]
        tail = s[last.end():].strip()
        # Chỉ thay nếu phần đuôi đủ ý nghĩa (chứa số/biến/=)
        if tail and (re.search(r'[=\d]', tail) or len(tail) >= 3):
            s = tail

    # Strip leading "Từ ..., Vì ..., Do ..." khi sau đó có dấu phẩy
    s = re.sub(
        r'^\s*(?:Từ|Vì|Do(?:\s+đó)?|Khi\s+đó|Theo|Áp\s+dụng)\s+[^,]+,\s*',
        '',
        s,
        flags=re.IGNORECASE,
    )

    # Strip trailing junk
    s = re.sub(r'[,;:]\s*$', '', s).strip()

    # Cap display options without cutting a meaningful parenthetical/clause in half.
    max_len = 180
    if len(s) > max_len:
        cut = max(s.rfind('.', 0, max_len), s.rfind(';', 0, max_len))
        if cut < 70:
            cut = s.rfind(',', 0, max_len)
        if cut < 70:
            cut = s.rfind(' ', 0, max_len)
        if cut < 70:
            cut = max_len
        s = s[:cut + 1].rstrip(' ,;:')

    s = _repair_dangling_option_text(s)

    return s.strip()


def _repair_dangling_option_text(text: str) -> str:
    """Best-effort repair for option text cut at a dangling parenthetical."""
    s = (text or '').strip()
    if not s:
        return s
    if s.count('(') > s.count(')'):
        last_open = s.rfind('(')
        if last_open >= max(0, len(s) - 80):
            s = s[:last_open].rstrip(' ,;:')
    s = re.sub(
        r'\s+(?:không|khong|vì|vi|do|nên|nen|thì|thi|bằng|bang|là|la)\s*$',
        '',
        s,
        flags=re.IGNORECASE,
    )
    return s.strip()


def _is_option_text_complete(text: str) -> bool:
    s = (text or '').strip()
    if not s:
        return False
    low = s.lower()
    if re.match(r'^(?:ra|bằng|bang|là|la)\s+[-+−]?\d+(?:[.,/]\d+)?\.?$', low):
        return False
    math_short = (
        bool(re.fullmatch(r'[\d\s+\-−*/^().,=√π∞]+', s))
        or bool(re.fullmatch(r'\\\(.+\\\)', s))
        or bool(re.fullmatch(r'(?:DNE|undefined|inf|infty)', s, re.IGNORECASE))
    )
    if len(s) < 6 and not math_short:
        return False
    if len(s) > 220:
        return False
    if s.count('(') != s.count(')'):
        return False
    if s.count('[') != s.count(']'):
        return False
    if s.count('{') != s.count('}'):
        return False
    trailing_bad = (
        ' không', ' khong', ' vì', ' vi', ' do', ' nên', ' nen', ' thì', ' thi',
        ' bằng', ' bang', ' là', ' la', ' ra', ' therefore', ' because',
    )
    if any(low.endswith(x) for x in trailing_bad):
        return False
    if re.search(r'[,;:]\s*$', s):
        return False
    return True


def record_option_text_issues(record: Dict[str, Any]) -> List[str]:
    """Return final formatted option/stem issues that should not reach output."""
    issues: List[str] = []
    options = record.get('options') or []
    if len(options) != 4:
        issues.append(f'options_count={len(options)}')
    answer_key = record.get('answer_key')
    keys = [o.get('key') for o in options]
    if answer_key not in keys:
        issues.append('answer_key_missing')
    stem = record.get('stem', '')
    stem_one_line = re.sub(r'\s+', ' ', str(stem))
    if re.search(r'\bA[.)]\s+.+\bB[.)]\s+.+\bC[.)]\s+.+\bD[.)]\s+', stem_one_line):
        issues.append('stem_contains_embedded_options')
    seen: set[str] = set()
    answer_text = ''
    for option in options:
        key = option.get('key', '?')
        text = option.get('text', '')
        if key == answer_key:
            answer_text = str(text)
        if str(text).strip().upper().rstrip('.)') in {'A', 'B', 'C', 'D'}:
            issues.append(f'option_{key}_is_choice_label')
        if not _is_option_text_complete(text):
            issues.append(f'option_{key}_incomplete')
        norm = re.sub(r'\s+', ' ', str(text).strip().lower())
        if norm in seen:
            issues.append(f'option_{key}_duplicate_text')
        seen.add(norm)
    answer_norm = re.sub(r'[.;:,\s]+$', '', re.sub(r'\s+', ' ', answer_text.lower())).strip()
    for option in options:
        if option.get('key') == answer_key:
            continue
        other_norm = re.sub(
            r'[.;:,\s]+$',
            '',
            re.sub(r'\s+', ' ', str(option.get('text', '')).lower()),
        ).strip()
        if len(answer_norm) >= 8 and len(other_norm) >= 8:
            if other_norm in answer_norm or answer_norm in other_norm:
                issues.append(f'option_{option.get("key", "?")}_subsumes_answer')
    if not stem or not str(stem).strip():
        issues.append('empty_stem')
    return issues


def _clean_stem_text(text: str) -> str:
    """Cleaner cho stem: cho phép dài hơn (≤ 400 chars)."""
    return _clean_display_text(text, max_len=400)


def to_question_record(slot: Dict[str, Any],
                       candidate: Dict[str, Any],
                       chunk: Dict[str, Any] = None,
                       year: int = None) -> Dict[str, Any]:
    """Chuyển candidate đã chọn → record đúng spec mục 18."""
    year = year or dt.datetime.utcnow().year
    qid = f'q_{year}_{uuid.uuid4().hex[:8]}'
    rng = random.Random(slot['slot_id'])  # deterministic shuffle theo slot_id

    answer_text = _clean_option_text(candidate['answer_text'])
    distractors = candidate['distractors']

    # Trộn 4 phương án ngẫu nhiên (deterministic theo slot_id)
    options_data = [{'text': answer_text, 'is_answer': True, 'error_type': None,
                     'rationale': _clean_display_text(
                         candidate.get('answer_explanation_text', ''), max_len=600)}]
    for d in distractors:
        # Xử lý error_type: chấp nhận null/None/'null'/'none'/'' từ LLM
        et = (d.get('distractor_category_text') or '').strip()
        if et.lower() in ('null', 'none', 'n/a', '', '-'):
            et = None
        options_data.append({
            'text': _clean_option_text(d['distractor_text']),
            'is_answer': False,
            'error_type': et,
            'rationale': _clean_display_text(
                d.get('distractor_explanation_text', ''), max_len=400),
        })
    rng.shuffle(options_data)

    keys = ['A', 'B', 'C', 'D']
    options = []
    answer_key = None
    explanation_per_distractor: Dict[str, str] = {}
    for k, o in zip(keys, options_data):
        options.append({'key': k, 'text': o['text'], 'error_type': o['error_type']})
        if o['is_answer']:
            answer_key = k
        else:
            explanation_per_distractor[k] = o['rationale']

    verification = candidate.get('_verification', {})

    # KC ids: ưu tiên verifier type (mô tả thao tác toán học thực tế của câu hỏi)
    # rồi đến question_pattern (planner gán). Tránh kc=compute_limit cho câu logic.
    kc_ids = []
    v_type = (candidate.get('_verification') or {}).get('engine', '')
    if v_type and v_type != 'none':
        kc_ids.append(v_type)
    pattern = slot.get('question_pattern', '')
    if pattern and pattern not in kc_ids:
        kc_ids.append(pattern)
    if not kc_ids:
        kc_ids = [slot.get('skill', '')]

    # Heuristic difficulty estimation (issue 6 — pre-deployment proxy cho IRT)
    diff_info = diff_mod.estimate(slot, candidate)

    return {
        'question_id': qid,
        'blueprint_slot_id': slot['slot_id'],
        'subject': 'Toán',
        'topic': slot.get('topic', ''),
        'kc_ids': kc_ids,
        'cognitive_level': slot['cognitive_level'],
        'difficulty_target': slot['difficulty_target'],
        'difficulty_estimated': diff_info['difficulty_estimated'],
        'difficulty_alignment': diff_info['difficulty_alignment'],
        'difficulty_features': diff_info['difficulty_features'],
        'discrimination': None,   # cần dữ liệu học sinh thật để tính
        'estimated_time_seconds': diff_info['estimated_time_seconds'],

        'question_type': slot.get('expected_question_type', 'single_choice'),
        'stem': _clean_stem_text(candidate['question_text']),
        'options': options,
        'answer_key': answer_key,

        'explanation_correct': _clean_display_text(
            candidate.get('answer_explanation_text', ''), max_len=800),
        'explanation_per_distractor': explanation_per_distractor,
        'hint': None,

        'visual': candidate.get('visual'),

        'source': {
            'doc_id': slot.get('doc_id'),
            'chunk_ids': (
                slot.get('selected_context_ids')
                or slot.get('selected_chunk_ids')
                or ([slot.get('doc_id')] if slot.get('doc_id') else [])
            ),
            'pages': (chunk or {}).get('pages', [])[:5],
            'quote': candidate.get('source_quote_text', ''),
            'quote_in_context': candidate.get('_quote_in_context'),
        },

        'verification': {
            'engine': verification.get('engine'),
            'method': verification.get('engine'),
            'verified': verification.get('verified'),
            'numeric_crosscheck_points': verification.get('numeric_crosscheck_points', 0),
            'detail': verification.get('detail'),
            'verified_at': dt.datetime.utcnow().isoformat() + 'Z',
        },

        'judging': {
            'grounding': candidate.get('_grounding'),
            'quality': candidate.get('_quality'),
            'bloom_alignment': candidate.get('_bloom_alignment'),
            'answer_prob': candidate.get('_answer_prob'),
            'quality_traits': candidate.get('_quality_traits') or {},
            'critic_skipped': candidate.get('_critic_skipped'),
        },

        'review': {
            'human_reviewed': False,
            'reviewed_by': None,
            'review_notes': None,
            'status': 'pending_review',
        },

        'tags': [slot.get('topic', ''), slot['question_pattern']],
        'version': 1,
    }


def reject_record(slot: Dict[str, Any], reason: str,
                  attempts: int = 1) -> Dict[str, Any]:
    qid = f'rej_{slot.get("slot_id", "unknown")}_{uuid.uuid4().hex[:8]}'
    return {
        'question_id': qid,
        'blueprint_slot_id': slot['slot_id'],
        'topic': slot.get('topic'),
        'doc_id': slot.get('doc_id'),
        'subject': 'Toán',
        'cognitive_level': slot.get('cognitive_level'),
        'difficulty_target': slot.get('difficulty_target'),
        'question_type': slot.get('expected_question_type', 'single_choice'),
        'stem': '',
        'options': [],
        'answer_key': None,
        'source': {
            'doc_id': slot.get('doc_id'),
            'chunk_ids': (
                slot.get('selected_context_ids')
                or slot.get('selected_chunk_ids')
                or ([slot.get('doc_id')] if slot.get('doc_id') else [])
            ),
            'pages': [],
            'quote': '',
            'quote_in_context': None,
        },
        'verification': {
            'engine': None,
            'method': None,
            'verified': None,
            'numeric_crosscheck_points': 0,
            'detail': None,
            'verified_at': None,
        },
        'judging': {
            'grounding': None,
            'quality': None,
            'bloom_alignment': None,
            'answer_prob': None,
            'quality_traits': {},
        },
        'review': {
            'human_reviewed': False,
            'reviewed_by': None,
            'review_notes': None,
            'status': 'rejected',
        },
        'review_status': 'rejected',
        'status': 'rejected',
        'reject_reason': reason,
        'attempts': attempts,
        'tags': [slot.get('topic', ''), slot.get('question_pattern', '')],
        'version': 1,
    }
