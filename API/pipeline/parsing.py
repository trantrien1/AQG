"""Shared parsing and display-normalization helpers for LLM outputs."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def extract_between(text: str, start: str, end: Optional[str]) -> str:
    s = text.find(start)
    if s < 0:
        return ''
    s += len(start)
    e = text.find(end, s) if end else len(text)
    if e < 0:
        e = len(text)
    return text[s:e].strip()


def parse_verifier_hint(block: str) -> Dict[str, Any]:
    m_type = re.search(r'type\s*:\s*(\S+)', block)
    m_payload = re.search(
        r'payload\s*:\s*(\{.*?\}|\[.*?\]|none|None|null)\s*$',
        block,
        re.DOTALL | re.MULTILINE,
    )
    if not m_payload:
        m_payload = re.search(r'payload\s*:\s*(\{.*\})', block, re.DOTALL)
    hint_type = m_type.group(1).strip() if m_type else 'none'
    payload_raw = m_payload.group(1).strip() if m_payload else '{}'
    try:
        payload = json.loads(payload_raw) if payload_raw not in ('none', 'None', 'null') else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {'type': hint_type, 'payload': payload}


def parse_visual_block(block: str) -> Optional[Dict[str, Any]]:
    m_type = re.search(r'type\s*:\s*(\S+)', block)
    m_spec = re.search(r'spec\s*:\s*(\{.*?\}|\[.*?\])\s*$', block, re.DOTALL | re.MULTILINE)
    if not m_spec:
        m_spec = re.search(r'spec\s*:\s*(\{.*\})', block, re.DOTALL)
    m_alt = re.search(r'alt_text\s*:\s*(.+)', block)
    visual_type = m_type.group(1).strip() if m_type else 'none'
    spec_raw = m_spec.group(1).strip() if m_spec else '{}'
    try:
        spec = json.loads(spec_raw)
    except Exception:
        spec = {}
    alt = m_alt.group(1).strip() if m_alt else ''
    if visual_type == 'none':
        return None
    return {'type': visual_type, 'spec': spec, 'alt_text': alt}


def clean_source_quote(quote: str) -> str:
    quote = (quote or '').strip()
    quote = quote.strip('"“”')
    return quote.strip()


_JSON_BAD_BACKSLASH_RE = re.compile(r'\\(?!["\\/bfnrtu])')
_JSON_LATEX_BACKSLASH_RE = re.compile(
    r'(?<!\\)\\(?=(?:frac|sqrt|binom|int|sum|prod|lim|sin|cos|tan|cot|sec|csc|'
    r'log|ln|exp|left|right|cdot|times|mathrm|text|operatorname|[(),;!]))'
)
_INLINE_MATH_RE = re.compile(r'(\\\(.+?\\\)|\$\$.+?\$\$|\$(?!\$).+?\$)', re.DOTALL)
_LATEX_COMMAND_RE = re.compile(
    r'\\(?:frac|sqrt|binom|int|sum|prod|lim|sin|cos|tan|cot|sec|csc|log|ln|exp)\b'
)

def loads_json_maybe_repair(raw: str) -> Any:
    """Parse JSON, repairing common unescaped LaTeX backslashes if needed."""
    raw = raw or ''
    latex_repaired = _JSON_LATEX_BACKSLASH_RE.sub(r'\\\\', raw)
    try:
        return json.loads(latex_repaired)
    except Exception:
        repaired = _JSON_BAD_BACKSLASH_RE.sub(r'\\\\', latex_repaired)
        if repaired == latex_repaired:
            raise
        return json.loads(repaired)

def _strip_math_delimiters(expr: str) -> str:
    s = (expr or '').strip()
    if s.startswith(r'\(') and s.endswith(r'\)'):
        return s[2:-2].strip()
    if s.startswith('$$') and s.endswith('$$'):
        return s[2:-2].strip()
    if s.startswith('$') and s.endswith('$'):
        return s[1:-1].strip()
    return s

def _to_latex_expr(expr: str) -> str:
    s = _strip_math_delimiters(str(expr or ''))
    if not s:
        return s

    def repl_factorial(match: re.Match[str]) -> str:
        arg = match.group(1).strip()
        if re.fullmatch(r'[A-Za-z_]\w*|\d+(?:[.,]\d+)?', arg):
            return f'{arg}!'
        return f'({arg})!'

    s = s.replace('**', '^')
    s = re.sub(
        r'\bbinomial\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)',
        r'\\binom{\1}{\2}',
        s,
    )
    s = re.sub(
        r'\bC\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)',
        r'\\binom{\1}{\2}',
        s,
    )
    s = re.sub(r'\bfactorial\s*\(\s*([^()]+?)\s*\)', repl_factorial, s)
    s = re.sub(r'\bsqrt\s*\(\s*([^()]+?)\s*\)', r'\\sqrt{\1}', s)
    s = re.sub(
        r'(?<!\\)\b(sin|cos|tan|cot|sec|csc|log|ln|exp)\s*\(',
        r'\\\1(',
        s,
    )
    s = re.sub(r'(?<=[\w}\]])\s*\*\s*(?=[\w{(\\])', r' \\cdot ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _inline_math(expr: str) -> str:
    s = _to_latex_expr(expr)
    if not s:
        return s
    return rf'\({s}\)'

def _looks_like_whole_math(text: str) -> bool:
    s = (text or '').strip()
    if not s or len(s) > 160:
        return False
    if re.fullmatch(r'[-+−]?\d+(?:[.,]\d+)?', s):
        return False
    if re.search(r'[À-ỹĐđ]', s):
        return False
    has_signal = bool(
        _LATEX_COMMAND_RE.search(s)
        or re.search(r'(?:\*\*|\^|[=<>≤≥√∫∑]|[A-Za-z0-9]\s*[+\-*/]\s*[A-Za-z0-9])', s)
    )
    if not has_signal:
        return False
    words = re.findall(r'[A-Za-z]{2,}', s)
    math_words = {
        'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'log', 'ln', 'exp', 'sqrt',
        'binomial', 'frac', 'int', 'lim', 'dx', 'dy', 'dt',
    }
    non_math_words = [w for w in words if w.lower() not in math_words]
    return len(non_math_words) == 0

def normalize_display_math(text: str) -> str:
    """Normalize display text toward inline LaTeX while preserving meaning.

    Backward-compatible replacement for the old "SymPy to natural" display
    cleanup. It preserves existing LaTeX and converts common SymPy/plain math
    leaks such as sqrt(x), binomial(n,k), factorial(n), and **.
    """
    if not text:
        return text
    s = str(text).replace('**', '^')
    placeholders: list[str] = []

    def stash(expr: str) -> str:
        placeholders.append(_inline_math(expr))
        return f'@@MATH{len(placeholders) - 1}@@'

    s = _INLINE_MATH_RE.sub(lambda m: stash(m.group(0)), s)

    plain_patterns = [
        r'\bsqrt\s*\(\s*[^()]+?\s*\)\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\bbinomial\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\bC\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\bbinomial\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)',
        r'\bC\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)',
        r'\bfactorial\s*\(\s*[^()]+?\s*\)',
        r'\bsqrt\s*\(\s*[^()]+?\s*\)',
    ]
    for pattern in plain_patterns:
        s = re.sub(pattern, lambda m: stash(m.group(0)), s)

    latex_patterns = [
        r'\\frac\s*\{[^{}]+?\}\s*\{[^{}]+?\}\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\\sqrt\s*\{[^{}]+?\}\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\\binom\s*\{[^{}]+?\}\s*\{[^{}]+?\}\s*=\s*[-+]?\d+(?:[.,]\d+)?',
        r'\\frac\s*\{[^{}]+?\}\s*\{[^{}]+?\}',
        r'\\sqrt\s*\{[^{}]+?\}',
        r'\\binom\s*\{[^{}]+?\}\s*\{[^{}]+?\}',
        r'\\int\b[^,.;:\n]+?d[A-Za-z]',
    ]
    for pattern in latex_patterns:
        s = re.sub(pattern, lambda m: stash(m.group(0)), s)

    s = re.sub(
        r'(?<![\w\\])([A-Za-z0-9]\w*(?:\^\{?[-+]?\w+\}?)?'
        r'(?:\s*[+\-]\s*(?:\d+(?:[.,]\d+)?|[A-Za-z]\w*(?:\^\{?[-+]?\w+\}?)?))*'
        r'\s*=\s*[-+]?\d+(?:[.,]\d+)?)',
        lambda m: stash(m.group(1)),
        s,
    )
    s = re.sub(
        r'(?<![\w\\])([A-Za-z0-9]\w*\^\{?[-+]?\w+\}?(?:\s*[+\-]\s*\d+)?)',
        lambda m: stash(m.group(1)),
        s,
    )
    s = re.sub(r'(∫[^,.;:\n]+?d[A-Za-z])', lambda m: stash(m.group(1)), s)

    if not placeholders and _looks_like_whole_math(s):
        return _inline_math(s)

    for i, expr in enumerate(placeholders):
        s = s.replace(f'@@MATH{i}@@', expr)
    return re.sub(r'\s+', ' ', s).strip()

def sympy_to_natural(text: str) -> str:
    return normalize_display_math(text)


_extract = extract_between
_parse_verifier_hint = parse_verifier_hint
_parse_visual_block = parse_visual_block
_clean_source_quote = clean_source_quote
_sympy_to_natural = sympy_to_natural
