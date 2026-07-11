"""Distractor and option validators reused by Direct_PDF_Mode."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import config as cfg
from .iwf_checker import run_iwf_checks
from .schema import _clean_option_text, _is_option_text_complete
from .llm_client import get_embeddings


# ==== Cosine similarity ====

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


# ==== Distractor validator (má»¥c 14) ====

def _check_unique_answer(response: Dict[str, Any]) -> bool:
    """ÄÃ¡p Ã¡n khÃ´ng trÃ¹ng vá»›i distractor nÃ o."""
    ans = response['answer_text'].strip().lower()
    for d in response['distractors']:
        if d['distractor_text'].strip().lower() == ans:
            return False
    return True


def _check_length_balance(response: Dict[str, Any]) -> bool:
    """Tá»‰ sá»‘ dÃ i/ngáº¯n nháº¥t giá»¯a cÃ¡c phÆ°Æ¡ng Ã¡n khÃ´ng quÃ¡ 3.5Ã—.

    Math distractors khÃ¡c Ä‘á»™ dÃ i tá»± nhiÃªn (sá»‘ ngáº¯n vs cÃ´ng thá»©c dÃ i). Chá»‰
    catch extreme imbalance â€” Ä‘Ã¡p Ã¡n dÃ i gáº¥p nhiá»u láº§n distractor lÃ  smell
    cá»§a "giveaway" (há»c sinh Ä‘oÃ¡n Ä‘Ã¡p Ã¡n dÃ i nháº¥t)."""
    options = [response['answer_text']] + [d['distractor_text'] for d in response['distractors']]
    lens = [len(o.strip()) for o in options if o and o.strip()]
    if len(lens) < 4:
        return False
    short, long_ = min(lens), max(lens)
    if short == 0:
        return False
    return (long_ / short) <= 3.5


def _check_anti_pattern(response: Dict[str, Any]) -> bool:
    """Cáº¥m 'Táº¥t cáº£ Ä‘á»u Ä‘Ãºng' / 'KhÃ´ng cÃ³ Ä‘Ã¡p Ã¡n nÃ o' trong distractor."""
    bad = ['táº¥t cáº£ cÃ¡c phÆ°Æ¡ng Ã¡n', 'khÃ´ng cÃ³ phÆ°Æ¡ng Ã¡n', 'all of the above',
           'none of the above', 'táº¥t cáº£ Ä‘Ã¡p Ã¡n']
    for d in response['distractors']:
        t = d['distractor_text'].lower()
        if any(b in t for b in bad):
            return False
    return True


import re as _re

# Bá»™ rule: keyword trong stem â†’ expected visual type.
# Náº¿u stem chá»©a keyword mÃ  visual khÃ´ng pháº£i type tÆ°Æ¡ng á»©ng â†’ reject.
_VISUAL_REF_RULES = [
    (_re.compile(r'\bbáº£ng\s+chÃ¢n\s+(lÃ½|trá»‹)\b', _re.I),                'truth_table'),
    (_re.compile(r'\bbáº£ng\s+(sau|trÃªn|dÆ°á»›i|Ä‘Ã£\s+cho)\b', _re.I),       'truth_table'),
    (_re.compile(r'\bma\s+tráº­n\s+(sau|trÃªn|Ä‘Ã£\s+cho|nÃ o)\b', _re.I),   'matrix'),
    (_re.compile(r'\b(Ä‘á»“\s+thá»‹|graph)\s+(sau|trÃªn|Ä‘Ã£\s+cho|nÃ o|vá»›i\s+cÃ¡c)\b', _re.I),
                                                                       'graph_network'),
    (_re.compile(r'\b(sá»‘\s+Ä‘á»‰nh|sá»‘\s+cáº¡nh|báº­c\s+Ä‘á»‰nh)\b.{0,30}\b(sau|trÃªn|Ä‘Ã£\s+cho)\b',
                _re.I | _re.S),                                        'graph_network'),
    (_re.compile(r'\bcÃ¢y\s+(sau|trÃªn|Ä‘Ã£\s+cho|nÃ o)\b', _re.I),         'tree'),
    (_re.compile(r'\b(sÆ¡\s+Ä‘á»“\s+venn|biá»ƒu\s+Ä‘á»“\s+venn)\b', _re.I),     'venn_diagram'),
    (_re.compile(r'\b(dá»±a\s+vÃ o|theo|quan\s+sÃ¡t|xem)\s+hÃ¬nh\b', _re.I),'function_graph'),
]


def _expected_visual_type(stem: str) -> Optional[str]:
    """Tráº£ vá» type visual mÃ  stem Ä‘ang yÃªu cáº§u (náº¿u cÃ³); None náº¿u stem khÃ´ng
    cáº§n visual."""
    for pat, vt in _VISUAL_REF_RULES:
        if pat.search(stem):
            return vt
    return None


def _check_visual_consistency(response: Dict[str, Any]) -> bool:
    """Stem-ref â†” visual type pháº£i khá»›p.
    - Stem yÃªu cáº§u type T mÃ  visual=None â†’ fail
    - Stem yÃªu cáº§u type T mÃ  visual.type â‰  T â†’ fail
    - Stem KHÃ”NG yÃªu cáº§u nhÆ°ng visual cÃ³ â†’ OK (extra info)
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
    """Visual spec internal consistency: kiá»ƒm cÃ¡c trÆ°á»ng báº¯t buá»™c theo type."""
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
        # má»—i row cÃ³ Ä‘á»§ keys cho variables
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
    return True   # type láº¡, khÃ´ng validate sÃ¢u


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
    text = text.replace('âˆ’', '-').replace('Â·', '*')
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
        r'[-+âˆ’]?\d+(?:[.,]\d+)?(?:\s*/\s*[-+âˆ’]?\d+(?:[.,]\d+)?)?',
        raw,
    ))
    candidates.extend(_re.findall(
        r'(?:C|P)\s*\([^)]{1,60}\)|[A-Za-zÃ€-á»¹ÄÄ‘]\w*(?:\s*[+\-âˆ’*/^]\s*[A-Za-zÃ€-á»¹ÄÄ‘0-9().]+)+',
        raw,
    ))

    for cand in reversed(candidates):
        fixed = _clean_option_text(cand,).strip()
        if fixed and len(fixed) <= max_len and _is_option_text_complete(fixed):
            return fixed
    return s

_NUMERIC_OPTION_RE = r'[-+âˆ’]?\d+(?:[.,]\d+)?(?:\s*/\s*[-+âˆ’]?\d+(?:[.,]\d+)?)?'

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
        ' nÃª', ' nÃªn', ' vÃ¬', ' do', ' báº±ng', ' lÃ ', ' ra', ' thÃ¬',
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
    """Distractor khÃ´ng quÃ¡ giá»‘ng nhau (cosine < threshold)."""
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
    """Tráº£ vá» dict cÃ¡c check pass/fail.

    Triáº¿t lÃ½ (theo user feedback): heuristic rules KHÃ”NG override agent judgment.
    - HARD checks (reject náº¿u fail): unique_answer, anti_pattern, display_syntax,
      visual_consistency, visual_spec_valid, iwf_no_duplicate_distractor,
      iwf_distractor_min_length. ÄÃ¢y lÃ  correctness/format basics.
    - SOFT checks (chá»‰ warning, KHÃ”NG Ä‘Æ°a vÃ o all_passed): length_balance,
      iwf_format_consistency, iwf_numeric_scale, iwf_no_absolute_terms.
      Multi-trait CriticAgent (distractor_plausibility) lÃ  gate thá»±c sá»±.
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

    # all_passed chá»‰ tÃ­nh HARD checks (soft checks chá»‰ lÃ  annotation)
    checks['all_passed'] = all(v for k, v in hard_checks.items())
    return checks


