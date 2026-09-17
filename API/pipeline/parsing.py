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


# Model hay escape thừa backslash của delimiter trong JSON ("\\\\(" thay vì
# "\\(") -> text sau json.loads chứa "\\(", KaTeX không nhận và để sót
# backslash mồ côi trong math span. Thu gọn mọi run >=2 backslash đứng ngay
# trước ( ) [ ] về đúng một dấu \.
_EXTRA_DELIM_BACKSLASH_RE = re.compile(r'\\{2,}(?=[()\[\]])')
_DISPLAY_MATH_RE = re.compile(r'(\\\[[\s\S]+?\\\]|\$\$[\s\S]+?\$\$)', re.DOTALL)
_INLINE_MATH_RE = re.compile(r'(\\\(.+?\\\)|\$(?!\$).+?\$)', re.DOTALL)
_INNER_MATH_DELIMITER_RE = re.compile(r'\\[()\[\]]|\$\$?')
_LATEX_COMMAND_RE = re.compile(
    r'\\(?:frac|sqrt|binom|int|sum|prod|lim|sin|cos|tan|cot|sec|csc|log|ln|exp)\b'
)

def _robust_json_repair(text: str) -> str:
    """Escape every unescaped LaTeX backslash inside JSON string literals, in a
    single left-to-right pass that never re-processes what it just wrote.

    The old two-regex approach failed whenever an escaped delimiter and a
    non-whitelisted command appeared together (e.g. ``\\(`` next to ``\\pi``):
    it raised ``Invalid \\escape`` on the un-whitelisted command and silently
    turned ``\\theta``/``\\beta``/``\\nabla`` into control characters. The
    scanner handles the whole LaTeX vocabulary uniformly. Inside a string:

      * ``\\"`` ``\\\\`` ``\\/``          -> valid escape, kept
      * ``\\uXXXX`` (4 hex digits)        -> kept
      * ``\\b \\f \\n \\r \\t`` followed   -> a real control-char escape, kept
        by a non-letter
      * everything else, including those  -> a LaTeX command (``\\theta``,
        five before a letter (``\\theta``)   ``\\frac``, ``\\circ``, ``\\(``,
        and ``\\(`` ``\\pi`` ``\\,`` ...     ``\\,`` ...) -> backslash doubled

    Correct for input that is already partly escaped (``\\\\(`` stays) as well
    as fully unescaped (``\\(`` -> ``\\\\(``).
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == '"':
            out.append(ch)
            in_str = False
            i += 1
            continue
        if ch == '\\':
            nxt = text[i + 1] if i + 1 < n else ''
            after = text[i + 2] if i + 2 < n else ''
            if nxt == 'u' and re.match(r'[0-9a-fA-F]{4}', text[i + 2:i + 6]):
                out.append(text[i:i + 6])
                i += 6
                continue
            if nxt in '"\\/':                       # already-valid escape
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            if nxt in 'bfnrt' and not after.isalpha():
                out.append(ch)                      # real \n \t (not \theta)
                out.append(nxt)
                i += 2
                continue
            out.append('\\\\')                      # LaTeX backslash -> double
            i += 1
            continue
        if ch < ' ':
            # Ký tự điều khiển THÔ nằm trong chuỗi JSON: json.loads ném
            # "Invalid control character". Một số model xuống dòng thật ngay
            # giữa lời giải thay vì viết \n. Escape lại thay vì bỏ cả câu —
            # nếu không, cái trông như "model sinh kém" thật ra chỉ là bộ parse
            # của ta khắt khe hơn model khác một chút.
            out.append({'\n': '\\n', '\r': '\\r', '\t': '\\t'}.get(
                ch, '\\u%04x' % ord(ch)))
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def loads_json_maybe_repair(raw: str) -> Any:
    """Parse JSON, repairing unescaped LaTeX backslashes if needed.

    Fast path: already-valid JSON parses unchanged (the scanner never touches
    it). Otherwise `_robust_json_repair` escapes the LaTeX backslashes the model
    leaves raw (``\\(``, ``\\frac``, ``\\pi``, ``\\theta``, ``\\circ`` ...) and
    we retry; if the input is broken for some other reason the retry re-raises.
    """
    raw = raw or ''
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        return json.loads(_robust_json_repair(raw))
    except Exception:
        _dump_unparsable(raw)
        raise


def _dump_unparsable(raw: str) -> None:
    """Ghi output thô không parse nổi ra đĩa khi AQG_DEBUG_RAW_DIR được đặt.

    Khi quét nhiều mô hình, "0 câu giao ra" mà không có output thô thì không
    phân biệt được model viết JSON sai với bộ parse của ta khắt khe. Mặc định
    tắt, không ảnh hưởng đường chạy thường.
    """
    import os
    target = os.getenv('AQG_DEBUG_RAW_DIR')
    if not target:
        return
    try:
        import hashlib
        import pathlib
        d = pathlib.Path(target)
        d.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:12]
        (d / f'unparsable-{name}.txt').write_text(raw, encoding='utf-8')
    except Exception:
        pass

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

def _repair_math_inner(expr: str) -> str:
    s = str(expr or '')
    s = _INNER_MATH_DELIMITER_RE.sub('', s)
    s = re.sub(r'\\,\s*(d[A-Za-z])', r'\\,\1', s)
    # Backslash mồ côi cuối span (tàn dư của delimiter escape thừa) làm KaTeX
    # báo parse error cả span — cắt bỏ.
    s = re.sub(r'\\+\s*$', '', s)
    return s

def _repair_math_span(expr: str) -> str:
    s = str(expr or '')
    if s.startswith(r'\[') and s.endswith(r'\]'):
        return rf'\[{_repair_math_inner(s[2:-2])}\]'
    if s.startswith('$$') and s.endswith('$$'):
        return f'$${_repair_math_inner(s[2:-2])}$$'
    if s.startswith(r'\(') and s.endswith(r'\)'):
        return rf'\({_repair_math_inner(s[2:-2])}\)'
    if s.startswith('$') and s.endswith('$'):
        return rf'\({_repair_math_inner(s[1:-1])}\)'
    return s

def normalize_latex_escapes(text: str) -> str:
    """Thu gọn backslash escape thừa trước delimiter toán: '\\\\(' -> '\\('.

    Dùng cho text đã qua json.loads mà model escape quá tay. Idempotent.
    """
    if not text:
        return text
    return _EXTRA_DELIM_BACKSLASH_RE.sub(r'\\', str(text))


def trim_unclosed_math(text: str) -> str:
    """Cắt bỏ math span mở '\\(' mà không có '\\)' đóng phía sau.

    Thường do bước cap độ dài cắt ngang giữa công thức — phần TeX cụt sẽ
    hiện thô/đỏ trên KaTeX nên bỏ hẳn span dở còn hơn giữ.
    """
    if not text:
        return text
    s = str(text)
    while True:
        last_open = s.rfind(r'\(')
        if last_open == -1 or s.find(r'\)', last_open + 2) != -1:
            break
        s = s[:last_open].rstrip()
    # Backslash mồ côi cuối chuỗi (tàn dư delimiter bị cắt/escape thừa).
    return re.sub(r'\\+$', '', s).rstrip()


def drop_orphan_math_closers(text: str) -> str:
    """Bỏ '\\)' mồ côi — không có '\\(' mở tương ứng phía trước.

    Model đôi khi đóng span hai lần ('...\\frac{x^2}{4}\\)\\)'); inline math
    không lồng nhau nên mọi '\\)' gặp lúc depth=0 chắc chắn là rác hiển thị
    (KaTeX không render, học sinh thấy '\\)' thô trong đề).
    """
    if not text or r'\)' not in str(text):
        return text
    s = str(text)
    out: list[str] = []
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        two = s[i:i + 2]
        if two == r'\(':
            depth += 1
            out.append(two)
            i += 2
        elif two == r'\)':
            if depth > 0:
                depth -= 1
                out.append(two)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _repair_nested_math_delimiters(text: str) -> str:
    s = str(text or '')
    s = _DISPLAY_MATH_RE.sub(lambda m: _repair_math_span(m.group(0)), s)
    return _INLINE_MATH_RE.sub(lambda m: _repair_math_span(m.group(0)), s)

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
    s = _EXTRA_DELIM_BACKSLASH_RE.sub(r'\\', str(text).replace('**', '^'))
    s = _repair_nested_math_delimiters(s)
    # '\)' đóng thừa nằm NGOÀI span (vd '...x^2\)\)') — regex span ở trên không
    # đụng tới nên phải quét riêng sau khi các span hợp lệ đã được sửa.
    s = drop_orphan_math_closers(s)
    placeholders: list[str] = []

    def stash(expr: str, *, preserve_math_span: bool = False) -> str:
        placeholders.append(_repair_math_span(expr) if preserve_math_span else _inline_math(expr))
        return f'@@MATH{len(placeholders) - 1}@@'

    s = _DISPLAY_MATH_RE.sub(lambda m: stash(m.group(0), preserve_math_span=True), s)
    s = _INLINE_MATH_RE.sub(lambda m: stash(m.group(0), preserve_math_span=True), s)

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
        r'\\int\b[^,.;:\n]+?d[A-Za-z]\s*=\s*[-+]?\d+(?:[.,]\d+)?',
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
    return _repair_nested_math_delimiters(re.sub(r'\s+', ' ', s).strip())

def sympy_to_natural(text: str) -> str:
    return normalize_display_math(text)


_extract = extract_between
_parse_verifier_hint = parse_verifier_hint
_parse_visual_block = parse_visual_block
_clean_source_quote = clean_source_quote
_sympy_to_natural = sympy_to_natural
