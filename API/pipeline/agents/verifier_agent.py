"""VerifierAgent — kiểm tra symbolic + distractor validator cho 1 candidate.

Agent làm việc trên COPY của candidate để thread-safe khi chạy song song
với CriticAgent. Trả về VerifyResponse với annotations dict riêng biệt.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict

from .base import BaseAgent
from .messages import VerifyRequest, VerifyResponse
from ..verifier import verify, verify_distractor, VerificationResult, _natural_to_sympy
from ..filter import option_text_sanity_issues, repair_option_texts, validate_distractors
from ..rule_validator import first_issue_code, validate_candidate

_QUOTE_REPAIR_CODES = {
    'quote_mismatch:source_quote_not_relevant',
    'quote_mismatch:source_quote_is_metadata',
}

def _expected_from_answer(answer_text: str):
    """Best-effort numeric claim extraction for verifier payloads missing expected."""
    if not answer_text:
        return None
    text = str(answer_text)
    if '=' in text:
        text = text.split('=')[-1]
    text = text.replace('−', '-')

    # Vietnamese thousands-grouping: "600.000" / "1.234.567" use '.' as the
    # thousands separator, not a decimal point. Two-or-more dot-groups of
    # exactly 3 digits are unambiguous; a single group is only collapsed when
    # a currency/scale word confirms it (otherwise "600.000" would misread as
    # the float 600.0 instead of 600000, causing a spurious verifier mismatch).
    # Must run BEFORE stripping \text{...}, since the currency word (e.g.
    # "đồng") is often itself inside a \text{} unit wrapper.
    def _collapse_vn_thousands(m: 're.Match') -> str:
        return m.group(0).replace('.', '')
    text = re.sub(r'\b\d{1,3}(?:\.\d{3}){2,}\b', _collapse_vn_thousands, text)
    if re.search(r'(?i)đồng|vnd|nghìn|triệu', text):
        text = re.sub(r'\b\d{1,3}\.\d{3}\b', _collapse_vn_thousands, text)

    # Strip LaTeX text-mode wrappers (unit labels like \text{m}, \text{đồng})
    # entirely before any other cleanup. Otherwise the generic char-strip below
    # keeps ASCII letters (it only removes non-alnum chars), so leftover
    # command names like "text" leak into the string and break sympy parsing
    # — the previous fallback regex then grabbed only a numerator, e.g. reading
    # "\frac{352}{3}\,\text{m}" as 352 instead of 352/3.
    # Consume the unit's exponent together with the wrapper: "\text{m}^3"
    # must not leave a dangling "^3" that later attaches to the number
    # (e.g. "128 m^3" misreading as 128**3).
    text = re.sub(
        r'\\(?:text|mathrm|operatorname|mbox)\s*\{[^{}]*\}'
        r'(?:\s*\^\s*(?:\{\s*\d+\s*\}|\d+))?',
        ' ', text)
    text = re.sub(r'\\(?:,|;|!|quad|qquad)', ' ', text)

    # \pi → pi với phép nhân tường minh ("432\pi" nghĩa là 432*π). Nếu không,
    # \dfrac{432\pi}{5} rơi xuống fallback và bị đọc thành 432 thay vì
    # 432π/5 ≈ 271.43 → answer_text_mismatch reject oan câu đúng. Nhân tường
    # minh cả khi \pi đứng sau '}' hoặc ')' ("\frac{81}{10}\pi" = (81/10)*π —
    # thiếu thì sympify fail, fallback đọc thành 81).
    text = re.sub(r'([\d)}])\s*\\pi\b', r'\1*pi', text)
    text = re.sub(r'\\pi\b', 'pi', text)

    _num = r'[-+]?(?:\d+(?:\.\d+)?(?:\*pi)?|pi)'
    text = re.sub(
        r'\\d?frac\s*\{\s*(' + _num + r')\s*\}\s*\{\s*(' + _num + r')\s*\}',
        r'(\1)/(\2)',
        text,
    )
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)
    text = re.sub(
        r'\b(?:[cdk]?m|mm)(?:\s*\^\s*\{?\s*\d\s*\}?|[²³23])?(?![A-Za-z0-9])',
        ' ', text, flags=re.I)
    text = re.sub(r'\b(?:đơn vị|units?)\b', ' ', text, flags=re.I)
    text = re.sub(r'[^0-9A-Za-z_+\-*/().^ ]+', ' ', text).strip()
    # Any unit stripped above may still orphan its exponent (" ^2" from
    # "s^2", "km/h^2"...) — drop it, otherwise it binds to the number.
    text = re.sub(r'(?<=[\d).])\s+\^\s*\d+(?:\.\d+)?', ' ', text).strip()
    if not text:
        return None
    try:
        import sympy
        value = sympy.sympify(_natural_to_sympy(text)).evalf()
        as_float = float(value)
        return int(as_float) if abs(as_float - int(as_float)) < 1e-12 else as_float
    except Exception:
        m = re.search(r'-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?', text)
        if not m:
            return None
        raw = m.group(0).replace(' ', '')
        try:
            if '/' in raw:
                a, b = raw.split('/', 1)
                return float(a) / float(b)
            return float(raw)
        except Exception:
            return None

def _safe_payload(raw) -> dict:
    """Coerce payload to dict — LLM sometimes returns string instead of object."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if raw:
            import json as _json
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}
    return {}


def _fill_missing_expected(hint: Dict[str, Any], answer_text: str) -> Dict[str, Any]:
    hint = copy.deepcopy(hint) if isinstance(hint, dict) else {}
    t = hint.get('type', 'none')
    payload = _safe_payload(hint.get('payload'))
    expected = _expected_from_answer(answer_text)
    if expected is None:
        return hint
    if t in ('analytic_geometry', 'probability', 'counting', 'modular') and 'expected' not in payload:
        payload['expected'] = int(expected) if t in ('counting', 'modular') else expected
    elif t == 'numeric_eval' and 'expected_numeric' not in payload:
        payload['expected_numeric'] = expected
    elif t == 'limit' and 'claimed_value' not in payload:
        payload['claimed_value'] = expected
    else:
        return hint
    hint['payload'] = payload
    return hint

def _verified_numeric_value(result: VerificationResult):
    value = result.actual if result.actual is not None else result.expected
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            import sympy
            return float(sympy.sympify(value).evalf())
        except Exception:
            return None

def _numeric_close(a, b) -> bool:
    try:
        af = float(a)
        bf = float(b)
    except Exception:
        return False
    tol = max(1e-6, abs(bf) * 1e-4)
    return abs(af - bf) <= tol

def _answer_text_matches_verifier(
    verifier_type: str,
    answer_text: str,
    result: VerificationResult,
) -> bool:
    numeric_types = {'probability', 'counting', 'limit', 'numeric_eval', 'modular'}
    if verifier_type not in numeric_types or result.verified is not True:
        return True
    expected = _verified_numeric_value(result)
    claimed = _expected_from_answer(answer_text)
    if expected is None or claimed is None:
        return True
    try:
        claimed_f = float(claimed)
    except Exception:
        return True
    tol = max(1e-6, abs(expected) * 1e-4)
    return abs(claimed_f - expected) <= tol

def _solution_text(candidate: Dict[str, Any]) -> str:
    parts = [
        str(candidate.get('answer_explanation_text') or ''),
        str(candidate.get('why_correct') or ''),
    ]
    detailed = candidate.get('detailed_solution')
    if isinstance(detailed, dict):
        parts.append(str(detailed.get('final_answer') or ''))
        for step in detailed.get('steps') or []:
            if isinstance(step, dict):
                parts.append(str(step.get('content') or ''))
    return '\n'.join(parts)

def _fold_for_quote(text: str) -> str:
    import unicodedata
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()

def _quote_tokens(text: str) -> set[str]:
    stop = {
        'topic', 'title', 'chunk', 'type', 'context', 'clean', 'source',
        'quote', 'candidates', 'relevant', 'formulas', 'definitions',
        'theorems', 'worked', 'examples', 'note', 'use', 'anti', 'copy',
        'cau', 'bai', 'hoi', 'chon', 'dap', 'phuong', 'an', 'mot', 'cac',
        'trong', 'sau', 'voi', 'duoc', 'tinh', 'tim', 'la', 'co', 'cho',
    }
    folded = _fold_for_quote(text)
    return {
        t for t in re.findall(r'[a-z0-9]{3,}', folded)
        if t not in stop
    }

def _looks_like_metadata_quote(line: str) -> bool:
    return bool(re.match(
        r'(?i)^\s*(?:topic|title|summary|chunk type|use note|anti-copy note|'
        r'clean context text|source quote candidates|relevant formulas|'
        r'key definitions|key theorems|worked examples)\s*:',
        line or '',
    ) or re.search(
        r'(?i)\b(?:chunk type|use note|anti-copy note|questionable skills)\s*:',
        line or '',
    ) or 'he thong bai tap' in _fold_for_quote(line)
        or 'picture text' in _fold_for_quote(line))

def _looks_like_old_exercise_quote(line: str) -> bool:
    folded = _fold_for_quote(line)
    return bool(
        re.search(r'\b(?:cau|bai|question|exercise)\s*\d+[\.:)]?', folded)
        or re.search(
            r'\b(?:chon|dap an|phuong an|trac nghiem|hoi|bao nhieu|'
            r'khang dinh|dung sai|loi giai|context|page)\b',
            folded,
        )
    )

def _context_quote_candidates(context: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    raw_lines = re.split(r'[\n\r]+', context or '')
    for raw in raw_lines:
        line = re.sub(r'^\s*[-*•]\s*', '', str(raw or '').strip())
        line = re.sub(r'\s+', ' ', line).strip()
        if not line or len(line) < 15 or len(line) > 260:
            continue
        if _looks_like_metadata_quote(line) or _looks_like_old_exercise_quote(line):
            continue
        key = _fold_for_quote(line)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out[:80]

def _repair_source_quote_from_context(
    candidate: Dict[str, Any],
    slot: Dict[str, Any],
    context: str,
) -> tuple[bool, list[str]]:
    if not context:
        return False, []
    original = str(candidate.get('source_quote_text') or '').strip()
    qa_text = ' '.join([
        str(candidate.get('question_text') or ''),
        str(candidate.get('answer_text') or ''),
        str(candidate.get('answer_explanation_text') or ''),
        _solution_text(candidate),
        str(slot.get('topic') or ''),
        str(slot.get('skill') or ''),
    ])
    qa_tokens = _quote_tokens(qa_text)
    if not qa_tokens:
        return False, []

    current_issues = validate_candidate(candidate, slot)
    best: tuple[int, int, str, list[str]] | None = None
    for quote in _context_quote_candidates(context):
        if quote == original:
            continue
        quote_tokens = _quote_tokens(quote)
        overlap = len(quote_tokens & qa_tokens)
        has_math = 1 if re.search(r'(?:\\int|∫||\uf0f2|=|\^|\d)', quote) else 0
        if overlap < 1 and not has_math:
            continue
        trial = copy.copy(candidate)
        trial['source_quote_text'] = quote
        issues = validate_candidate(trial, slot)
        if any(issue in _QUOTE_REPAIR_CODES for issue in issues):
            continue
        score = overlap * 10 + has_math * 3 - len(issues) * 20
        item = (score, overlap, quote, issues)
        if best is None or item[:2] > best[:2]:
            best = item

    if best is None:
        return False, current_issues
    _score, _overlap, quote, issues = best
    if len(issues) > len(current_issues):
        return False, current_issues
    candidate['source_quote_text'] = quote
    candidate['_source_quote_repaired'] = True
    return True, issues

def _solution_supports_value(candidate: Dict[str, Any], expected) -> bool:
    detailed = candidate.get('detailed_solution')
    if isinstance(detailed, dict):
        final_answer = str(detailed.get('final_answer') or '').strip()
        if final_answer:
            final_claim = _expected_from_answer(final_answer)
            return final_claim is not None and _numeric_close(final_claim, expected)
    return False

def _numeric_text_variants(value) -> list[str]:
    try:
        number = float(value)
    except Exception:
        return []
    variants: set[str] = set()
    if abs(number - round(number)) < 1e-10:
        base = str(int(round(number)))
        variants.update({base, f'{base}.0', f'{base},0'})
    else:
        compact = f'{number:.12g}'
        variants.add(compact)
        variants.add(compact.replace('.', ','))
        for digits in (1, 2, 3):
            fixed = f'{number:.{digits}f}'.rstrip('0').rstrip('.')
            if fixed:
                variants.add(fixed)
                variants.add(fixed.replace('.', ','))
    return sorted((v for v in variants if v), key=len, reverse=True)

def _format_numeric_for_explanation(value, prefer_comma: bool = False) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number - round(number)) < 1e-10:
        out = str(int(round(number)))
    else:
        out = f'{number:.12g}'
    return out.replace('.', ',') if prefer_comma else out

def _replace_numeric_claim(text: str, old_value, new_value, prefer_comma: bool) -> str:
    out = str(text or '')
    replacement = _format_numeric_for_explanation(new_value, prefer_comma=prefer_comma)
    for variant in _numeric_text_variants(old_value):
        escaped = re.escape(variant).replace('\\-', r'[-\u2212]')
        if variant.startswith('-'):
            pattern = rf'(?<![\d.,]){escaped}(?![\d.,])'
        else:
            # Do not rewrite the magnitude inside an already-correct negative value.
            pattern = rf'(?<![\d.,\-\u2212]){escaped}(?![\d.,])'
        out = re.sub(pattern, replacement, out)
    return out

def _rewrite_repaired_solution_text(
    candidate: Dict[str, Any],
    old_answer: str,
    new_answer: str,
    old_value,
    new_value,
) -> None:
    """Keep verifier-repaired candidates internally consistent."""
    prefer_comma = ',' in new_answer

    def rewrite(text: str) -> str:
        out = str(text or '')
        if old_answer and any(ch.isalpha() for ch in old_answer):
            out = re.sub(re.escape(old_answer), lambda _m: new_answer, out)
        return _replace_numeric_claim(out, old_value, new_value, prefer_comma)

    for key in ('answer_explanation_text', 'why_correct'):
        if candidate.get(key):
            candidate[key] = rewrite(candidate[key])

    detailed = candidate.get('detailed_solution')
    if isinstance(detailed, dict):
        detailed['final_answer'] = new_answer
        for step in detailed.get('steps') or []:
            if isinstance(step, dict) and step.get('content'):
                step['content'] = rewrite(step.get('content', ''))

def _repair_answer_from_verified_distractor(
    candidate: Dict[str, Any],
    verifier_type: str,
    result: VerificationResult,
) -> bool:
    numeric_types = {'probability', 'counting', 'limit', 'numeric_eval', 'modular'}
    if verifier_type not in numeric_types or result.verified is not True:
        return False
    expected = _verified_numeric_value(result)
    if expected is None:
        return False
    current = _expected_from_answer(candidate.get('answer_text', ''))
    if current is not None and _numeric_close(current, expected):
        return False
    if not _solution_supports_value(candidate, expected):
        return False

    matches = []
    for idx, distractor in enumerate(candidate.get('distractors') or []):
        if not isinstance(distractor, dict):
            continue
        claim = _expected_from_answer(distractor.get('distractor_text', ''))
        if claim is not None and _numeric_close(claim, expected):
            matches.append((idx, distractor))
    if len(matches) != 1:
        return False

    _idx, matched = matches[0]
    old_answer = str(candidate.get('answer_text') or '').strip()
    new_answer = str(matched.get('distractor_text') or '').strip()
    if not old_answer or not new_answer:
        return False

    candidate['answer_text'] = new_answer
    _rewrite_repaired_solution_text(
        candidate,
        old_answer=old_answer,
        new_answer=new_answer,
        old_value=current,
        new_value=expected,
    )

    matched['distractor_text'] = old_answer
    if current is not None and _numeric_close(current, -float(expected)):
        matched['distractor_explanation_text'] = (
            f"Sai vì nhầm dấu kết quả, lấy {old_answer} thay vì {new_answer}."
        )
    else:
        matched['distractor_explanation_text'] = (
            f"Sai vì phép tính kiểm chứng cho {new_answer}, không phải {old_answer}."
        )
    matched['distractor_category_text'] = (
        matched.get('distractor_category_text') or 'answer_key_mismatch_repair'
    )
    candidate['_auto_repaired_answer_from_verifier'] = True
    return True

def _normalize_hint_schema(hint: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common LLM verifier schema aliases before verification."""
    hint = copy.deepcopy(hint) if isinstance(hint, dict) else {}
    t = hint.get('type', 'none')
    payload = _safe_payload(hint.get('payload'))
    if t == 'modular':
        op = payload.get('operation')
        aliases = {
            'modular_exponentiation': 'mod_pow',
            'modular_power': 'mod_pow',
            'pow_mod': 'mod_pow',
            'remainder': 'mod',
            'modulo': 'mod',
        }
        if op in aliases:
            payload['operation'] = aliases[op]
        elif not op:
            if {'base', 'exp', 'mod'}.issubset(payload):
                payload['operation'] = 'mod_pow'
            elif {'a', 'mod'}.issubset(payload):
                payload['operation'] = 'mod'
    elif t == 'probability':
        if 'formula' not in payload and 'expr' in payload:
            payload['formula'] = payload['expr']
    elif t == 'numeric_eval':
        # Model hay dùng alias khác 'expr' -> map về đúng key, tránh KeyError
        # khiến verifier fallback và formatter cap quality oan.
        if payload.get('expr') is None:
            for alias in ('expression', 'formula', 'value_expr', 'calc',
                          'computation'):
                if payload.get(alias) is not None:
                    payload['expr'] = payload[alias]
                    break
    elif t == 'analytic_geometry':
        op = payload.get('operation')
        aliases = {
            'point_plane_distance': 'distance_point_plane_3d',
            'distance_point_plane': 'distance_point_plane_3d',
            'point_line_distance': 'distance_point_line_2d',
            'distance_point_line': 'distance_point_line_2d',
        }
        if op in aliases:
            payload['operation'] = aliases[op]
    hint['payload'] = payload
    return hint


class VerifierAgent(BaseAgent):
    """Chạy 3 bước kiểm tra độc lập:

    1. Symbolic verify (SymPy / NetworkX) — kiểm đáp án đúng về mặt toán
    2. Multi-answer check — đảm bảo không distractor nào cũng được verify đúng
    3. Distractor validator — unique / length_balance / anti_pattern / visual
    """

    def __init__(self, use_skills: bool = True):
        super().__init__('verifier', use_skills=use_skills)

    def run(self, request: VerifyRequest) -> VerifyResponse:
        # Làm việc trên bản copy để tránh race condition với CriticAgent
        c: Dict[str, Any] = copy.copy(request.candidate)
        c['distractors'] = [
            copy.copy(d) for d in request.candidate.get('distractors', [])
        ]
        rule_issues = validate_candidate(c, request.slot)
        annotations: Dict[str, Any] = {'_rule_validator': {'issues': rule_issues}}
        if any(issue in _QUOTE_REPAIR_CODES for issue in rule_issues):
            repaired, repaired_issues = _repair_source_quote_from_context(
                c, request.slot, request.context,
            )
            if repaired:
                annotations['_source_quote_repaired'] = True
                annotations.setdefault('_candidate_patch', {})['source_quote_text'] = c.get('source_quote_text', '')
                annotations['_rule_validator'] = {
                    'issues': repaired_issues,
                    'repaired_from': rule_issues,
                }
                rule_issues = repaired_issues
        if rule_issues:
            code = first_issue_code(rule_issues)
            return VerifyResponse(
                annotations=annotations,
                rejected=True,
                reject_reason=f'{code}: rule validator failed: {rule_issues}',
            )

        hint = _normalize_hint_schema(c.get('verifier_hint', {}))
        hint = _fill_missing_expected(hint, c.get('answer_text', ''))

        # --- 1. Symbolic verify ---
        v_result: VerificationResult = verify(hint)
        annotations['_verification'] = {
            'verified': v_result.verified,
            'engine': v_result.engine,
            'detail': v_result.detail,
            'numeric_crosscheck_points': v_result.numeric_crosscheck_points,
        }

        # verified=False KHÔNG reject: LLM hiếm khi sai phép tính, mismatch ở
        # đây thường do verifier_hint (expr/expected_numeric) viết lệch câu hỏi
        # hoặc đáp án bị làm tròn → reject sẽ loại oan câu đúng. Giữ annotation
        # _verification.verified=False để Critic và bước chọn ứng viên (ưu tiên
        # verified=True) tự cân nhắc.
        if not _answer_text_matches_verifier(
            hint.get('type', 'none'),
            c.get('answer_text', ''),
            v_result,
        ):
            if _repair_answer_from_verified_distractor(
                c, hint.get('type', 'none'), v_result,
            ):
                annotations['_answer_key_repaired'] = True
                annotations['_candidate_patch'] = {
                    'answer_text': c.get('answer_text', ''),
                    'distractors': c.get('distractors', []),
                    'detailed_solution': c.get('detailed_solution'),
                    'answer_explanation_text': c.get('answer_explanation_text', ''),
                    'why_correct': c.get('why_correct', ''),
                }
            else:
                return VerifyResponse(
                    annotations=annotations,
                    rejected=True,
                    reject_reason=(
                        f'verifier=False (answer_text_mismatch: '
                        f'{c.get("answer_text", "")[:80]} vs {v_result.actual})'
                    ),
                )

        # Verifier chạy nhưng parse lỗi payload → fallback: cho đi tiếp qua Critic
        # thay vì reject ngay. CriticAgent + _final_quality_filter sẽ quyết định.
        if v_result.verified is None and v_result.engine != 'none':
            annotations['_verifier_errored'] = True
            annotations['_verification']['detail'] = (
                f'fallback: {v_result.detail[:120]}'
            )

        # --- 2. Multi-answer check (chỉ khi verified=True) ---
        if v_result.verified is True:
            for d in c.get('distractors', []):
                if verify_distractor(hint, d['distractor_text']) is True:
                    return VerifyResponse(
                        annotations=annotations, rejected=True,
                        reject_reason=(
                            f'multi_answer: distractor "{d["distractor_text"][:40]}"'
                            f' cũng được verifier xác nhận đúng'
                        ),
                    )

        # --- 3. Distractor validator ---
        option_repairs = repair_option_texts(c)
        if option_repairs:
            annotations['_option_text_repairs'] = option_repairs
            annotations.setdefault('_candidate_patch', {}).update({
                'answer_text': c.get('answer_text', ''),
                'distractors': c.get('distractors', []),
            })

        checks = validate_distractors(c, skip_embedding=True)
        annotations['_validator'] = checks
        if not checks['all_passed']:
            failed = [k for k, v in checks.items() if not v and k != 'all_passed']
            detail = ''
            if 'option_text_sanity' in failed:
                detail = f' issues={option_text_sanity_issues(c)}'
            return VerifyResponse(
                annotations=annotations, rejected=True,
                reject_reason=f'distractor_validator failed: {failed}{detail}',
            )

        return VerifyResponse(annotations=annotations, rejected=False)
