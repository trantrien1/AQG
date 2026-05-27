"""Filter pipeline (mục 14 — distractor validator + dedup).

Pipeline cho 1 slot:
    candidates → verify (mục 11) → grounding (mục 16) → quality
    → distractor validator → NLI → dedup
    → trả về top 1 đã pass tất cả.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import config as cfg
from . import grounding as gj
from .iwf_checker import run_iwf_checks
from .schema import _clean_option_text, _is_option_text_complete
from .verifier import verify, verify_distractor, VerificationResult
from .llm_client import get_embeddings


# ==== Cosine similarity ====

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


# ==== Distractor validator (mục 14) ====

def _check_unique_answer(response: Dict[str, Any]) -> bool:
    """Đáp án không trùng với distractor nào."""
    ans = response['answer_text'].strip().lower()
    for d in response['distractors']:
        if d['distractor_text'].strip().lower() == ans:
            return False
    return True


def _check_length_balance(response: Dict[str, Any]) -> bool:
    """Tỉ số dài/ngắn nhất giữa các phương án không quá 3.5×.

    Math distractors khác độ dài tự nhiên (số ngắn vs công thức dài). Chỉ
    catch extreme imbalance — đáp án dài gấp nhiều lần distractor là smell
    của "giveaway" (học sinh đoán đáp án dài nhất)."""
    options = [response['answer_text']] + [d['distractor_text'] for d in response['distractors']]
    lens = [len(o.strip()) for o in options if o and o.strip()]
    if len(lens) < 4:
        return False
    short, long_ = min(lens), max(lens)
    if short == 0:
        return False
    return (long_ / short) <= 3.5


def _check_anti_pattern(response: Dict[str, Any]) -> bool:
    """Cấm 'Tất cả đều đúng' / 'Không có đáp án nào' trong distractor."""
    bad = ['tất cả các phương án', 'không có phương án', 'all of the above',
           'none of the above', 'tất cả đáp án']
    for d in response['distractors']:
        t = d['distractor_text'].lower()
        if any(b in t for b in bad):
            return False
    return True


import re as _re

# Bộ rule: keyword trong stem → expected visual type.
# Nếu stem chứa keyword mà visual không phải type tương ứng → reject.
_VISUAL_REF_RULES = [
    (_re.compile(r'\bbảng\s+chân\s+(lý|trị)\b', _re.I),                'truth_table'),
    (_re.compile(r'\bbảng\s+(sau|trên|dưới|đã\s+cho)\b', _re.I),       'truth_table'),
    (_re.compile(r'\bma\s+trận\s+(sau|trên|đã\s+cho|nào)\b', _re.I),   'matrix'),
    (_re.compile(r'\b(đồ\s+thị|graph)\s+(sau|trên|đã\s+cho|nào|với\s+các)\b', _re.I),
                                                                       'graph_network'),
    (_re.compile(r'\b(số\s+đỉnh|số\s+cạnh|bậc\s+đỉnh)\b.{0,30}\b(sau|trên|đã\s+cho)\b',
                _re.I | _re.S),                                        'graph_network'),
    (_re.compile(r'\bcây\s+(sau|trên|đã\s+cho|nào)\b', _re.I),         'tree'),
    (_re.compile(r'\b(sơ\s+đồ\s+venn|biểu\s+đồ\s+venn)\b', _re.I),     'venn_diagram'),
    (_re.compile(r'\b(dựa\s+vào|theo|quan\s+sát|xem)\s+hình\b', _re.I),'function_graph'),
]


def _expected_visual_type(stem: str) -> Optional[str]:
    """Trả về type visual mà stem đang yêu cầu (nếu có); None nếu stem không
    cần visual."""
    for pat, vt in _VISUAL_REF_RULES:
        if pat.search(stem):
            return vt
    return None


def _check_visual_consistency(response: Dict[str, Any]) -> bool:
    """Stem-ref ↔ visual type phải khớp.
    - Stem yêu cầu type T mà visual=None → fail
    - Stem yêu cầu type T mà visual.type ≠ T → fail
    - Stem KHÔNG yêu cầu nhưng visual có → OK (extra info)
    """
    stem = response.get('question_text', '')
    expected = _expected_visual_type(stem)
    visual = response.get('visual')
    if expected is None:
        return True
    if not visual:
        return False
    if visual.get('type') != expected:
        return False
    return True


def _check_visual_spec_valid(response: Dict[str, Any]) -> bool:
    """Visual spec internal consistency: kiểm các trường bắt buộc theo type."""
    visual = response.get('visual')
    if not visual:
        return True
    t = visual.get('type')
    spec = visual.get('spec') or {}
    if t == 'truth_table':
        vars_ = spec.get('variables') or []
        rows = spec.get('rows') or []
        if not vars_ or not rows:
            return False
        # mỗi row có đủ keys cho variables
        for r in rows:
            if not isinstance(r, dict):
                return False
            if any(v not in r for v in vars_):
                return False
        return True
    if t == 'matrix':
        rows = spec.get('rows') or []
        if not rows:
            return False
        n_cols = len(rows[0])
        return all(isinstance(r, list) and len(r) == n_cols for r in rows)
    if t in ('graph_network', 'tree'):
        edges = spec.get('edges') or []
        if not edges:
            return False
        return all(isinstance(e, list) and len(e) >= 2 for e in edges)
    if t == 'venn_diagram':
        sets = spec.get('sets') or []
        return len(sets) >= 1
    return True   # type lạ, không validate sâu


def _check_display_syntax(response: Dict[str, Any]) -> bool:
    """Reject machine-only syntax leaking into student-facing text/options."""
    bad = ['**', 'binomial(', 'factorial(', 'Sum(', 'R**R']
    texts = [response.get('question_text', ''), response.get('answer_text', '')]
    texts.extend(d.get('distractor_text', '') for d in response.get('distractors', []))
    return not any(b in t for t in texts for b in bad)

def _stem_contains_embedded_options(stem: str) -> bool:
    text = _re.sub(r'\s+', ' ', stem or '')
    return _re.search(r'\bA[.)]\s+.+\bB[.)]\s+.+\bC[.)]\s+.+\bD[.)]\s+', text) is not None

def _normalize_option_compare(text: str) -> str:
    text = _clean_option_text(text or '').lower()
    text = text.replace('−', '-').replace('·', '*')
    text = _re.sub(r'\s+', ' ', text)
    text = _re.sub(r'[.;:,\s]+$', '', text)
    return text.strip()

def _check_candidate_structure(response: Dict[str, Any]) -> bool:
    """Reject malformed MCQ structure before judge calls."""
    if _stem_contains_embedded_options(response.get('question_text', '')):
        return False
    answer = _normalize_option_compare(response.get('answer_text', ''))
    if answer.upper() in {'A', 'B', 'C', 'D'}:
        return False
    for d in response.get('distractors', []):
        distractor = _normalize_option_compare(d.get('distractor_text', ''))
        if not distractor:
            return False
        # If a distractor is literally contained in the correct answer (or vice
        # versa), the item is usually ambiguous rather than a clean misconception.
        if len(answer) >= 8 and len(distractor) >= 8:
            if distractor in answer or answer in distractor:
                return False
    return True

def _salvage_option_text(text: str, max_len: int = 180) -> str:
    """Best-effort option repair before hard sanity checks.

    LLMs sometimes put a short final answer inside an explanatory fragment. Keep
    the final math/value-like span when the normal cleaner still leaves an
    incomplete option.
    """
    s = _clean_option_text(text or '')
    if _is_option_text_complete(s):
        return s

    raw = str(text or '').strip()
    candidates: List[str] = []
    if '=' in raw:
        candidates.append(raw.rsplit('=', 1)[-1])

    # Last numeric value or compact math expression is often the actual option.
    candidates.extend(_re.findall(
        r'[-+−]?\d+(?:[.,]\d+)?(?:\s*/\s*[-+−]?\d+(?:[.,]\d+)?)?',
        raw,
    ))
    candidates.extend(_re.findall(
        r'(?:C|P)\s*\([^)]{1,60}\)|[A-Za-zÀ-ỹĐđ]\w*(?:\s*[+\-−*/^]\s*[A-Za-zÀ-ỹĐđ0-9().]+)+',
        raw,
    ))

    for cand in reversed(candidates):
        fixed = _clean_option_text(cand,).strip()
        if fixed and len(fixed) <= max_len and _is_option_text_complete(fixed):
            return fixed
    return s

_NUMERIC_OPTION_RE = r'[-+−]?\d+(?:[.,]\d+)?(?:\s*/\s*[-+−]?\d+(?:[.,]\d+)?)?'

def _is_plain_numeric_option(text: str) -> bool:
    compact = _re.sub(r'\s+', '', str(text or ''))
    return bool(_re.fullmatch(_NUMERIC_OPTION_RE, compact))

def _extract_numeric_option(text: str) -> str:
    raw = str(text or '').strip()
    leading = _re.match(rf'^\s*({_NUMERIC_OPTION_RE})\b', raw)
    if leading:
        return _re.sub(r'\s+', '', leading.group(1))
    if '=' in raw:
        tail_nums = _re.findall(_NUMERIC_OPTION_RE, raw.rsplit('=', 1)[-1])
        if tail_nums:
            return _re.sub(r'\s+', '', tail_nums[-1])
    nums = _re.findall(_NUMERIC_OPTION_RE, raw)
    return _re.sub(r'\s+', '', nums[0]) if nums else ''

def repair_option_texts(response: Dict[str, Any]) -> List[str]:
    """Mutate candidate option texts into validator-ready concise forms."""
    changes: List[str] = []
    old_answer = response.get('answer_text', '')
    new_answer = _salvage_option_text(old_answer)
    if new_answer != old_answer:
        response['answer_text'] = new_answer
        changes.append(f'answer:{str(old_answer)[:60]} -> {new_answer[:60]}')

    answer_is_number = _is_plain_numeric_option(response.get('answer_text', ''))
    for idx, d in enumerate(response.get('distractors', []), start=1):
        old = d.get('distractor_text', '')
        new = _salvage_option_text(old)
        if answer_is_number and not _is_plain_numeric_option(new):
            numeric = _extract_numeric_option(old)
            if numeric:
                new = numeric
        if new != old:
            d['distractor_text'] = new
            changes.append(f'd{idx}:{str(old)[:60]} -> {new[:60]}')
    return changes

def option_text_sanity_issues(response: Dict[str, Any]) -> List[str]:
    trailing_bad = (
        ' nê', ' nên', ' vì', ' do', ' bằng', ' là', ' ra', ' thì',
        'therefore', 'because',
    )
    labelled = [('answer', _clean_option_text(response.get('answer_text', '')))]
    labelled.extend(
        (f'd{idx}', _clean_option_text(d.get('distractor_text', '')))
        for idx, d in enumerate(response.get('distractors', []), start=1)
    )

    issues: List[str] = []
    for label, text in labelled:
        s = (text or '').strip()
        if not s:
            issues.append(f'{label}:empty')
            continue
        if not _is_option_text_complete(s):
            issues.append(f'{label}:incomplete:{s[:80]}')
        if len(s) > 220:
            issues.append(f'{label}:too_long:{len(s)}')
        low = s.lower()
        if any(low.endswith(x) for x in trailing_bad):
            issues.append(f'{label}:dangling_tail:{s[-40:]}')
        if s.count('(') != s.count(')'):
            issues.append(f'{label}:paren_balance:{s[:80]}')
    return issues

def _check_option_text_sanity(response: Dict[str, Any]) -> bool:
    """Reject visibly broken or overlong answer-option text."""
    return not option_text_sanity_issues(response)


def _check_distractor_similarity(response: Dict[str, Any]) -> bool:
    """Distractor không quá giống nhau (cosine < threshold)."""
    texts = [d['distractor_text'] for d in response['distractors']]
    if len(texts) < 2:
        return True
    embs = get_embeddings(texts)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _cosine(embs[i], embs[j]) >= cfg.DISTRACTOR_SIMILARITY_THRESHOLD:
                return False
    return True


def validate_distractors(response: Dict[str, Any], skip_embedding: bool = False) -> Dict[str, Any]:
    """Trả về dict các check pass/fail.

    Triết lý (theo user feedback): heuristic rules KHÔNG override agent judgment.
    - HARD checks (reject nếu fail): unique_answer, anti_pattern, display_syntax,
      visual_consistency, visual_spec_valid, iwf_no_duplicate_distractor,
      iwf_distractor_min_length. Đây là correctness/format basics.
    - SOFT checks (chỉ warning, KHÔNG đưa vào all_passed): length_balance,
      iwf_format_consistency, iwf_numeric_scale, iwf_no_absolute_terms.
      Multi-trait CriticAgent (distractor_plausibility) là gate thực sự.
    """
    iwf = run_iwf_checks(response)

    hard_checks = {
        'candidate_structure': _check_candidate_structure(response),
        'unique_answer': _check_unique_answer(response),
        'anti_pattern': _check_anti_pattern(response),
        'display_syntax': _check_display_syntax(response),
        'option_text_sanity': _check_option_text_sanity(response),
        'visual_consistency': _check_visual_consistency(response),
        'visual_spec_valid': _check_visual_spec_valid(response),
        'iwf_no_duplicate_distractor': iwf.get('iwf_no_duplicate_distractor', True),
        'iwf_misconception_category_diversity': iwf.get(
            'iwf_misconception_category_diversity', True,
        ),
        'iwf_distractor_min_length': iwf.get('iwf_distractor_min_length', True),
        'iwf_format_consistency': iwf.get('iwf_format_consistency', True),
    }
    soft_checks = {
        'length_balance': _check_length_balance(response),
        'iwf_numeric_scale': iwf.get('iwf_numeric_scale', True),
        'iwf_no_absolute_terms': iwf.get('iwf_no_absolute_terms', True),
    }
    checks: Dict[str, Any] = dict(hard_checks)
    checks.update({f'_soft_{k}': v for k, v in soft_checks.items()})

    if not skip_embedding:
        try:
            checks['distractor_diversity'] = _check_distractor_similarity(response)
        except Exception:
            checks['distractor_diversity'] = True

    # all_passed chỉ tính HARD checks (soft checks chỉ là annotation)
    checks['all_passed'] = all(v for k, v in hard_checks.items())
    return checks


# ==== NLI filter (mục 14) ====

def filter_by_nli(responses: List[Dict[str, Any]], context: str,
                  margin: float = cfg.NLI_PROB_MARGIN) -> List[Dict[str, Any]]:
    out = []
    for r in responses:
        q = r['question_text']
        ans_claim = f'"{r["answer_text"]}" là đáp án đúng cho câu hỏi: "{q}"'
        ans_prob = gj.judge_nli(context, ans_claim)
        r['_answer_prob'] = ans_prob
        ok = True
        for d in r['distractors']:
            d_claim = f'"{d["distractor_text"]}" là đáp án đúng cho câu hỏi: "{q}"'
            d_prob = gj.judge_nli(context, d_claim)
            d['_distractor_prob'] = d_prob
            if ans_prob - d_prob <= margin:
                ok = False
        if ok:
            out.append(r)
    return out


# ==== Dedup by question embedding ====

def dedupe_questions(responses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not responses:
        return []
    texts = [r['question_text'] + '\n' + r['answer_text'] for r in responses]
    try:
        embs = get_embeddings(texts)
    except Exception:
        return responses
    kept_idx = [0]
    for i in range(1, len(responses)):
        if all(_cosine(embs[i], embs[j]) < cfg.QUESTION_DEDUP_THRESHOLD for j in kept_idx):
            kept_idx.append(i)
    return [responses[i] for i in kept_idx]


# ==== Pipeline 1 slot ====

def filter_for_slot(candidates: List[Dict[str, Any]],
                    context: str,
                    slot: Dict[str, Any],
                    use_nli: bool = True,
                    reject_log: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Trả về candidate tốt nhất sau khi qua verifier + grounding + validator + (NLI).
    None nếu không có candidate nào pass.
    `reject_log` (nếu truyền) sẽ được append với reason của từng candidate fail."""
    scored = []
    for c in candidates:
        # 1. Symbolic verifier
        hint = c.get('verifier_hint', {})
        v_result: VerificationResult = verify(hint)
        c['_verification'] = {
            'verified': v_result.verified,
            'engine': v_result.engine,
            'detail': v_result.detail,
            'numeric_crosscheck_points': v_result.numeric_crosscheck_points,
        }
        if v_result.verified is False:
            c['_reject_reason'] = f'verifier=False ({v_result.engine}: {v_result.detail[:80]})'
            if reject_log is not None:
                reject_log.append(c.get('_reject_reason', 'unknown'))
            continue

        # Verifier ran but threw an exception (bad payload from LLM) → tag for needs_revision.
        # Phân biệt: engine='none' = không có verifier applicable (OK); engine!=none = verifier
        # đã thử nhưng lỗi parse → candidate không đủ tin cậy để vào pending_review.
        if v_result.verified is None and v_result.engine != 'none':
            c['_verifier_errored'] = True

        # 1b. Verifier UNIQUENESS — check không có distractor nào cũng đúng
        if v_result.verified is True:
            multi_answer = False
            for d in c.get('distractors', []):
                d_verified = verify_distractor(hint, d['distractor_text'])
                if d_verified is True:
                    multi_answer = True
                    c['_reject_reason'] = (
                        f'multi_answer: distractor "{d["distractor_text"][:40]}" '
                        f'cũng được verifier xác nhận đúng'
                    )
                    break
            if multi_answer:
                if reject_log is not None:
                    reject_log.append(c.get('_reject_reason', 'unknown'))
                continue

        # 2. Distractor validator
        repairs = repair_option_texts(c)
        if repairs:
            c['_option_text_repairs'] = repairs
        checks = validate_distractors(c, skip_embedding=True)
        c['_validator'] = checks
        if not checks['all_passed']:
            failed = [k for k, v in checks.items() if not v and k != 'all_passed']
            detail = ''
            if 'option_text_sanity' in failed:
                detail = f' issues={option_text_sanity_issues(c)}'
            c['_reject_reason'] = f'distractor_validator failed: {failed}{detail}'
            if reject_log is not None:
                reject_log.append(c.get('_reject_reason', 'unknown'))
            continue

        unsupported = gj.unsupported_stem_numbers(context, c)
        if unsupported:
            c['_grounding'] = 0.0
            c['_unsupported_stem_numbers'] = unsupported
            c['_reject_reason'] = f'unsupported stem numbers: {unsupported}'
            if reject_log is not None:
                reject_log.append(c.get('_reject_reason', 'unknown'))
            continue

        contradiction = gj.directional_contradiction(context, c)
        if contradiction:
            c['_grounding'] = 0.0
            c['_local_contradiction'] = contradiction
            c['_reject_reason'] = f'local contradiction: {contradiction}'
            if reject_log is not None:
                reject_log.append(c.get('_reject_reason', 'unknown'))
            continue

        # 3. Grounding (kiểm cả quote nằm trong context)
        try:
            g = gj.judge_grounding(context, c)
            c['_grounding'] = g
            if g < cfg.GROUNDING_THRESHOLD:
                in_ctx = c.get('_quote_in_context')
                c['_reject_reason'] = (
                    f'grounding={g:.2f} < {cfg.GROUNDING_THRESHOLD}'
                    + ('' if in_ctx else ' (quote KHÔNG nằm trong context)')
                )
                if reject_log is not None:
                    reject_log.append(c.get('_reject_reason', 'unknown'))
                continue
        except Exception as e:
            c['_grounding'] = None
            print(f'    grounding error: {e}')

        # 4. Quality
        try:
            q = gj.judge_quality(slot.get('topic', ''), slot['cognitive_level'], c)
            c['_quality'] = q
            if q < cfg.QUALITY_THRESHOLD:
                c['_reject_reason'] = f'quality={q:.2f} < {cfg.QUALITY_THRESHOLD}'
                if reject_log is not None:
                    reject_log.append(c.get('_reject_reason', 'unknown'))
                continue
        except Exception:
            c['_quality'] = 0.5

        scored.append(c)

    if not scored:
        return None

    # 5. NLI filter (đắt — chỉ chạy nếu cần và còn candidate)
    if use_nli and len(scored) > 1:
        try:
            scored = filter_by_nli(scored, context)
        except Exception as e:
            print(f'    NLI error: {e}')

    if not scored:
        return None

    # 6. Sort: verified=True → engine='none' (no verifier) → verifier errored
    scored.sort(key=lambda r: (
        0 if r['_verification']['verified'] is True else (2 if r.get('_verifier_errored') else 1),
        -(r.get('_quality') or 0),
        -(r.get('_grounding') or 0),
    ))
    return scored[0]
